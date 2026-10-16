"""AutoMix — salida de auriculares (PFL): escuchar un deck por otra placa de sonido sin mandarlo a los parlantes."""
import threading
from collections import deque
import numpy as np
import sounddevice as sd
from setup.ajustes import NIVEL_V2


class _Previa:
    """Reproducción propia de los auriculares para un deck: tiene su PROPIA posición y no toca al deck (no hace play,
    no dispara la mezcla automática ni suena en los parlantes)."""
    def __init__(self):
        self.audio = None
        self.pos = 0.0               # en muestras
        self.playing = False


class Auriculares:
    """Segunda salida de audio (por ejemplo un DAC USB). Recibe, bloque a bloque, el audio de los decks marcados
    (antes del crossfader, por eso se oye aunque a los parlantes no llegue nada) y lo reproduce por su propio dispositivo.
    Como son dos placas con relojes distintos, entre las dos hay una pequeña cola de amortiguación."""
    PREVIO = 3            # bloques que se juntan antes de empezar a sonar (evita cortes por llegar justo)
    MAX_BLOQUES = 8       # si se acumulan más, se descartan los más viejos (los relojes de las placas no son idénticos)

    def __init__(self, sr, bloque=1024):
        self.sr = sr
        self.bloque = bloque
        self.stream = None
        self.nombre = ""             # dispositivo abierto
        self.error = ""
        self.canales = 2
        self.GANANCIA = 3.5          # refuerzo propio de los auriculares (+11 dB): la salida principal queda igual
        self.vol = 0.8               # 0..1 (se aplica al cuadrado, como el volumen general)
        self.cue_a = False
        self.cue_b = False
        self.decks = {}              # {"A": deck, "B": deck} (los pone la ventana)
        self.prev = {"A": _Previa(), "B": _Previa()}
        self._cola = deque()
        self._lock = threading.Lock()
        self._sonando = False        # ya se juntó el colchón previo

    # ---- dispositivos -------------------------------------------------
    @staticmethod
    def listar():
        """[(índice, nombre para mostrar, canales, API de audio)] de todas las salidas. Las de la API que usa el programa
        van primero y con su nombre a secas; las de otras APIs (WASAPI, DirectSound) llevan [API] al final. Los auriculares
        Bluetooth a veces solo aparecen en alguna de ellas, o como mono (perfil de llamadas)."""
        res = []
        try:
            try:
                apis = sd.query_hostapis()
            except Exception:
                apis = []
            try:
                api_def = sd.default.hostapi
            except Exception:
                api_def = None
            for i, d in enumerate(sd.query_devices()):
                ch = int(d.get("max_output_channels", 0))
                if ch < 1:
                    continue
                ha = d.get("hostapi")
                api = apis[ha]["name"] if apis and ha is not None and 0 <= ha < len(apis) else ""
                if "WDM" in api or "ASIO" in api:
                    continue                                   # esas dos APIs son delicadas: no se ofrecen
                vis = d["name"] if (api_def is None or ha == api_def) else f"{d['name']} [{api}]"
                if ch == 1:
                    vis += " · mono"
                res.append((i, vis, ch, api, ha == api_def or api_def is None))
        except Exception:
            pass
        res.sort(key=lambda x: (not x[4], x[0]))
        return [(i, v, ch, api) for i, v, ch, api, _ in res]

    @property
    def activo(self):
        return self.stream is not None

    def abrir(self, indice, nombre="", canales=2, api=""):
        self.cerrar()
        try:
            extra = None
            if "WASAPI" in api:
                try:
                    extra = sd.WasapiSettings(auto_convert=True)     # que Windows adapte la frecuencia (44,1 → 48 kHz, etc.)
                except Exception:
                    extra = None
            self.canales = 1 if canales < 2 else 2
            self.stream = sd.OutputStream(samplerate=self.sr, channels=self.canales, dtype="float32", device=indice,
                                          callback=self._cb, blocksize=self.bloque, latency=0.15, extra_settings=extra)
            self.stream.start()
            self.nombre = nombre
            self.error = ""
            return True
        except Exception as e:
            self.stream = None
            self.nombre = ""
            self.error = str(e)
            return False

    def cerrar(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop(); s.close()
            except Exception:
                pass
        with self._lock:
            self._cola.clear()
            self._sonando = False

    # ---- audio ----------------------------------------------------------
    def alimentar(self, a, b):
        """Lo llama el callback principal con el audio de cada deck ya renderizado (antes del crossfader)."""
        if self.stream is None:
            return
        ca, cb = self.cue_a, self.cue_b
        pa, pb = self.prev["A"].playing, self.prev["B"].playing
        if not (ca or cb or pa or pb):
            if self._cola:
                with self._lock:
                    self._cola.clear(); self._sonando = False
            return
        cue = None
        for nom, vivo, flag in (("A", a, ca), ("B", b, cb)):
            if self.prev[nom].playing:                       # la previa propia reemplaza al deck en vivo
                x = self._render_previa(nom, len(a))
            else:
                x = vivo if flag else None
            if x is not None:
                cue = x if cue is None else cue + x
        if cue is None:
            return
        g = float(self.vol) ** 2
        cue = np.tanh(cue * (g * self.GANANCIA)).astype(np.float32)      # saturación suave: sube el volumen sin cortes feos
        with self._lock:
            self._cola.append(cue)
            while len(self._cola) > self.MAX_BLOQUES:
                self._cola.popleft()

    # ---- previa propia (play de auriculares) ----------------------------
    def previa_play(self, nom):
        """Empieza (o sigue) la previa del deck. La primera vez tras cargar un tema arranca donde está el deck."""
        d = self.decks.get(nom)
        p = self.prev[nom]
        if d is None or d.audio is None:
            return False
        if p.audio is not d.audio:
            p.audio = d.audio
            p.pos = float(d.cursor)
        if p.pos >= len(p.audio) - 2048:
            p.pos = 0.0
        p.playing = True
        return True

    def previa_pausa(self, nom):
        self.prev[nom].playing = False

    def previa_ir(self, nom, fraccion):
        p = self.prev[nom]
        d = self.decks.get(nom)
        if d is None or d.audio is None:
            return
        if p.audio is not d.audio:
            p.audio = d.audio
        p.pos = float(max(0.0, min(0.999, fraccion)) * len(p.audio))

    def previa_fraccion(self, nom):
        p = self.prev[nom]
        d = self.decks.get(nom)
        if d is None or d.audio is None or p.audio is not d.audio:
            return 0.0
        return p.pos / max(1, len(p.audio))

    def _render_previa(self, nom, frames):
        p = self.prev[nom]
        d = self.decks.get(nom)
        au = d.audio if d is not None else None
        if au is None or au is not p.audio:                  # se cargó otro tema: la previa se detiene
            p.playing = False
            return None
        rate = float(d.rate_eff)
        n = len(au)
        pos = p.pos + np.arange(frames, dtype=np.float64) * rate
        if pos[-1] + 2 >= n:
            p.playing = False
            ok = pos + 2 < n
            if not ok.any():
                return None
            pos = np.where(ok, pos, 0.0)
            valido = ok[:, None]
        else:
            valido = None
        i = pos.astype(np.int64)
        t = (pos - i).astype(np.float32)[:, None]
        y = au[i] * (1.0 - t) + au[i + 1] * t
        if valido is not None:
            y = y * valido
        else:
            p.pos += frames * rate
        return (y * (d.auto_gain * NIVEL_V2)).astype(np.float32)

    def _cb(self, outdata, frames, time_info, status):
        with self._lock:
            if not self._sonando:
                if len(self._cola) >= self.PREVIO:
                    self._sonando = True
            if not self._sonando:
                outdata[:] = 0
                return
            partes = []; falta = frames
            while falta > 0 and self._cola:
                blk = self._cola[0]
                if len(blk) <= falta:
                    partes.append(blk); self._cola.popleft(); falta -= len(blk)
                else:
                    partes.append(blk[:falta]); self._cola[0] = blk[falta:]; falta = 0
            if falta > 0:                      # se vació: vuelve a juntar el colchón
                partes.append(np.zeros((falta, 2), dtype=np.float32))
                self._sonando = False
        blk = np.concatenate(partes) if len(partes) > 1 else partes[0]
        if outdata.shape[1] == 1:                      # salida mono (Bluetooth en perfil de llamadas): mezcla L+R
            outdata[:, 0] = blk.mean(axis=1)
        else:
            outdata[:] = blk
