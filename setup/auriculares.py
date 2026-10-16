"""AutoMix — salida de auriculares (PFL): escuchar un deck por otra placa de sonido sin mandarlo a los parlantes."""
import threading
from collections import deque
import numpy as np
import sounddevice as sd


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
        self.vol = 0.8               # 0..1 (se aplica al cuadrado, como el volumen general)
        self.cue_a = False
        self.cue_b = False
        self._cola = deque()
        self._lock = threading.Lock()
        self._sonando = False        # ya se juntó el colchón previo

    # ---- dispositivos -------------------------------------------------
    @staticmethod
    def listar():
        """[(índice, nombre)] de las salidas estéreo de la misma API de audio que usa el programa."""
        res = []
        try:
            try:
                api = sd.default.hostapi
            except Exception:
                api = None
            for i, d in enumerate(sd.query_devices()):
                if d.get("max_output_channels", 0) >= 2 and (api is None or d.get("hostapi") == api):
                    res.append((i, d["name"]))
        except Exception:
            pass
        return res

    @property
    def activo(self):
        return self.stream is not None

    def abrir(self, indice, nombre=""):
        self.cerrar()
        try:
            self.stream = sd.OutputStream(samplerate=self.sr, channels=2, dtype="float32", device=indice,
                                          callback=self._cb, blocksize=self.bloque, latency=0.12)
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
        if not (ca or cb):
            if self._cola:
                with self._lock:
                    self._cola.clear(); self._sonando = False
            return
        cue = None
        if ca:
            cue = a
        if cb:
            cue = b if cue is None else cue + b
        g = float(self.vol) ** 2
        cue = np.clip(cue * g, -0.99, 0.99).astype(np.float32)
        with self._lock:
            self._cola.append(cue)
            while len(self._cola) > self.MAX_BLOQUES:
                self._cola.popleft()

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
        outdata[:] = np.concatenate(partes) if len(partes) > 1 else partes[0]
