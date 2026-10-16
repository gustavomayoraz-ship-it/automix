"""AutoMix — mezclador global (callback de audio) y grabación de la mezcla."""
from pathlib import Path
import math
import threading
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
from setup.auriculares import Auriculares
from setup.dsp import AutoMejora, CruceLR4, LimitadorSuave, RealceGrave, TonoAgudos, TonoMedios


class GrabadorMezcla:
    """Graba a un .wav (16 bits) exactamente lo que sale por los parlantes. El callback de audio solo encola una copia;
    un hilo aparte escribe en disco, así que grabar no puede producir cortes en el sonido."""
    def __init__(self, sr=44100):
        import queue
        self.sr = sr
        self.activo = False
        self.ruta = None
        self.muestras = 0
        self.perdidos = 0
        self._q = queue.Queue(maxsize=600)         # ~14 s de margen si el disco se atrasa
        self._hilo = None
        self._error = None

    def iniciar(self, carpeta):
        carpeta = Path(carpeta); carpeta.mkdir(parents=True, exist_ok=True)
        self.ruta = carpeta / time.strftime("AutoMix_%Y-%m-%d_%H-%M-%S.wav")
        self.muestras = 0; self.perdidos = 0; self._error = None
        while not self._q.empty():
            try: self._q.get_nowait()
            except Exception: break
        archivo = sf.SoundFile(str(self.ruta), mode="w", samplerate=self.sr, channels=2, subtype="PCM_16")
        self._hilo = threading.Thread(target=self._escribir, args=(archivo,), daemon=True)
        self.activo = True
        self._hilo.start()
        return self.ruta

    def escribir(self, bloque):               # lo llama el callback de audio: rápido y sin bloquear
        try:
            self._q.put_nowait(np.array(bloque, dtype=np.float32, copy=True))
            self.muestras += len(bloque)
        except Exception:
            self.perdidos += len(bloque)

    def _escribir(self, archivo):
        try:
            while True:
                b = self._q.get()
                if b is None:
                    break
                archivo.write(b)
        except Exception as e:
            self._error = str(e)
            self.activo = False
        finally:
            try: archivo.close()
            except Exception: pass

    def detener(self):
        """Corta la grabación y espera a que el disco termine. Devuelve (ruta, segundos)."""
        self.activo = False
        if self._hilo is not None:
            self._q.put(None)
            self._hilo.join(timeout=10)
            self._hilo = None
        return self.ruta, self.muestras / float(self.sr)

    @property
    def segundos(self):
        return self.muestras / float(self.sr)




class GlobalMixer:
    F_CRUCE = 150.0           # por debajo = "graves" (bombo y bajo)
    ESPERA_COMPAS_S = 2.5     # (respaldo) espera máxima de la línea de compás si no se conoce el BPM

    def __init__(self, deck_a, deck_b, sr=44100, blocksize=1024):
        self.deck_a = deck_a
        self.deck_b = deck_b
        self.sr = sr
        self.blocksize = blocksize
        self.stream = None
        self.snap_pos = None        # (pos A, pos B) en muestras, tomadas en el MISMO instante al final de cada bloque
        self.gain_obj = 1.0
        self._gain_act = 1.0
        self.mb = AutoMejora(sr)
        self.golpe = RealceGrave(sr)
        self.medios = TonoMedios(sr)
        self.agudos = TonoAgudos(sr)
        self.mb_activo = False
        self._mb_wet = 0.0
        self.banda_activa = False         # cruce por bandas (lo enciende la ventana)
        self._xo_a = CruceLR4(self.F_CRUCE, sr)
        self._xo_b = CruceLR4(self.F_CRUCE, sr)
        self._g = None                    # ganancias actuales: a_lo, a_hi, b_lo, b_hi
        self._swap_espera = 0.0
        self.limitador = LimitadorSuave(sr)
        self.comp_activo = True            # compensador de nivel (lo maneja la ventana)
        self._comp = 1.0                   # ganancia actual del compensador (1 = sin efecto)
        self._e = [0.0, 0.0, 0.0]          # energías suavizadas: deck A, deck B y la suma
        self.comp_db = 0.0
        self.vu = (0.0, 0.0, 1.0, 1.0)     # picos L, R (a la salida), ganancia del limitador y del compensador
        self.grabador = GrabadorMezcla(sr)
        self.aur = Auriculares(sr, blocksize)      # salida de auriculares (PFL)

    @staticmethod
    def _rampa(g0, g1, frames):
        if g0 == g1:
            return g1
        return np.linspace(g0, g1, frames, dtype=np.float32)[:, None]

    def _db_muestras(self, deck):
        an = deck.analysis
        if not an:
            return None
        c = deck._db_cache
        if c is None or c[0] is not an:
            db = an.get("downbeats_full") or an.get("downbeats") or []
            arr = np.asarray(db, dtype=np.float64) * float(deck.sr)
            deck._db_cache = c = (an, arr)
        return c[1] if len(c[1]) else None

    def _offset_compas(self, deck, p0, frames):
        """Índice de muestra, dentro de este bloque, donde el deck que sale cruza una línea de compás.
        None = no cae en este bloque · -1 = no hay grilla (se traspasa ya)."""
        arr = self._db_muestras(deck)
        if arr is None:
            return -1
        adv = frames * max(1e-6, deck.rate_eff)
        i = int(np.searchsorted(arr, p0, side="left"))
        if i < len(arr) and arr[i] < p0 + adv:
            return int(max(0, min(frames - 1, (arr[i] - p0) / max(1e-6, deck.rate_eff))))
        return None

    @staticmethod
    def _vec_paso(g0, g1, k, r, frames):
        v = np.full(frames, g0, dtype=np.float32)
        k = max(0, min(k, frames - r))
        v[k:k + r] = np.linspace(g0, g1, r, endpoint=True, dtype=np.float32)
        v[k + r:] = g1
        return v[:, None]

    def _ganancias_bajos(self, tg, frames, pa, pb):
        g = self._g
        a0, b0, a1, b1 = g["a_lo"], g["b_lo"], tg["a_lo"], tg["b_lo"]
        if a0 == a1 and b0 == b1:
            self._swap_espera = 0.0
            return a1, b1
        sale = self.deck_a if a1 < a0 else (self.deck_b if b1 < b0 else None)
        if sale is None:                                   # los dos suben (p. ej. un deck se detuvo): rampa suave
            g["a_lo"], g["b_lo"] = a1, b1
            return self._rampa(a0, a1, frames), self._rampa(b0, b1, frames)
        p0 = pa if sale is self.deck_a else pb
        k = self._offset_compas(sale, p0, frames)
        if k is None:
            self._swap_espera += frames / float(self.sr)
            try:
                compas_s = 4.0 * 60.0 / (float(sale.analysis["bpm"]) * max(1e-6, sale.rate_eff))
            except Exception:
                compas_s = self.ESPERA_COMPAS_S
            if self._swap_espera < compas_s * 1.25:        # un compás entero (y un poco más) siempre contiene una línea
                return a0, b0                              # todavía no: se espera la próxima línea de compás
            k = 0
        self._swap_espera = 0.0
        r = max(8, min(int(0.020 * self.sr), frames))      # ~20 ms (1 ciclo de un bajo): sin clic ni 'escalón'
        k = 0 if k < 0 else max(0, k - r)                  # la rampa TERMINA en la línea de compás: el bombo nuevo cae entero
        g["a_lo"], g["b_lo"] = a1, b1                      # el traspaso queda hecho en este bloque
        return self._vec_paso(a0, a1, k, r, frames), self._vec_paso(b0, b1, k, r, frames)

    TAU_E = 0.35        # ventana de energía (s)
    TAU_ATK = 0.30      # cuánto tarda en bajar la suma cuando suenan los dos (s)
    TAU_REL = 0.90      # y en volver cuando uno se va (s)
    COMP_MIN = 0.56     # como máximo -5 dB

    def _compensar(self, p_a, p_b, mix, frames):
        """Mantiene el nivel de la suma parecido al del más fuerte de los dos: si suenan juntos (y a pleno)
        la mezcla no sube sola. Se compara la energía de cada deck con la de la suma, así no depende de un nivel fijo."""
        dt = frames / float(self.sr)
        k = 1.0 - math.exp(-dt / self.TAU_E)
        e = self._e
        e[0] += (float(np.mean(p_a * p_a)) - e[0]) * k
        e[1] += (float(np.mean(p_b * p_b)) - e[1]) * k
        e[2] += (float(np.mean(mix * mix)) - e[2]) * k
        obj = 1.0
        if self.comp_activo and e[2] > 1e-8:
            obj = max(self.COMP_MIN, min(1.0, math.sqrt(max(e[0], e[1]) / e[2])))
        c0 = self._comp
        c1 = c0 + (obj - c0) * (1.0 - math.exp(-dt / (self.TAU_ATK if obj < c0 else self.TAU_REL)))
        self._comp = c1
        self.comp_db = 20.0 * math.log10(max(1e-3, c1))
        if abs(c1 - 1.0) < 1e-4 and abs(c0 - 1.0) < 1e-4:
            return mix
        return mix * np.linspace(c0, c1, frames, dtype=np.float32)[:, None]

    def _mezclar(self, a, b, frames, pa, pb):
        da, db = self.deck_a, self.deck_b
        tg = {"a_lo": da.vol_lo, "a_hi": da.vol_hi, "b_lo": db.vol_lo, "b_hi": db.vol_hi}
        if self._g is None:
            self._g = dict(tg)
        g = self._g
        if self.banda_activa:
            alo, ahi = self._xo_a.split(a)
            blo, bhi = self._xo_b.split(b)
            ga_lo, gb_lo = self._ganancias_bajos(tg, frames, pa, pb)
            p_a = alo * ga_lo + ahi * self._rampa(g["a_hi"], tg["a_hi"], frames)
            p_b = blo * gb_lo + bhi * self._rampa(g["b_hi"], tg["b_hi"], frames)
        else:
            p_a = a * self._rampa(g["a_hi"], tg["a_hi"], frames)
            p_b = b * self._rampa(g["b_hi"], tg["b_hi"], frames)
            g["a_lo"], g["b_lo"] = tg["a_hi"], tg["b_hi"]
        g["a_hi"], g["b_hi"] = tg["a_hi"], tg["b_hi"]
        mix = p_a + p_b
        try:
            mix = self._compensar(p_a, p_b, mix, frames)
        except Exception:
            self._comp = 1.0
        return mix

    def start(self, device=None):
        if self.stream is not None:
            return
        self.stream = sd.OutputStream(
            samplerate=self.sr, channels=2, dtype="float32",
            callback=self._cb, blocksize=self.blocksize, latency=0.12, device=device
        )
        self.stream.start()

    def reiniciar_audio(self):
        """PortAudio solo lista los dispositivos al iniciar: los que se enchufaron o conectaron (Bluetooth) después no
        aparecen. Esto cierra todo, vuelve a leer los dispositivos y reabre la salida principal en el MISMO dispositivo
        de antes (aunque Windows haya cambiado el predeterminado). Corta el sonido un instante."""
        nombre = api = None
        try:
            if self.stream is not None:
                d = sd.query_devices(self.stream.device)
                nombre = d["name"]; api = sd.query_hostapis(d["hostapi"])["name"]
        except Exception:
            pass
        try: self.aur.cerrar()
        except Exception: pass
        self.stop()
        try:
            sd._terminate(); sd._initialize()
        except Exception as e:
            print(f"[audio] no se pudo reiniciar PortAudio ({e})")
        idx = None
        try:
            if nombre:
                for i, d in enumerate(sd.query_devices()):
                    if d["name"] == nombre and d["max_output_channels"] >= 2 and sd.query_hostapis(d["hostapi"])["name"] == api:
                        idx = i; break
        except Exception:
            pass
        try:
            self.start(idx)
        except Exception:
            self.start(None)

    def set_volumen(self, v01):
        self.gain_obj = float(max(0.0, min(1.0, v01))) ** 2

    def stop(self):
        if self.stream:
            self.stream.stop(); self.stream.close(); self.stream = None

    def _cb(self, outdata, frames, time_info, status):
        pa = self.deck_a.cursor + self.deck_a._cursor_frac + self.deck_a.loop_desfase          # posición al INICIO del bloque (para caer en el compás)
        pb = self.deck_b.cursor + self.deck_b._cursor_frac + self.deck_b.loop_desfase
        a = self.deck_a.render(frames)
        b = self.deck_b.render(frames)
        self.snap_pos = (self.deck_a.cursor + self.deck_a._cursor_frac + self.deck_a.loop_desfase,
                         self.deck_b.cursor + self.deck_b._cursor_frac + self.deck_b.loop_desfase)
        try:
            self.aur.alimentar(a, b)
        except Exception:
            pass
        mix = self._mezclar(a, b, frames, pa, pb)
        w1 = 1.0 if self.mb_activo else 0.0
        if w1 > 0.0 or self._mb_wet > 0.0:
            try:
                proc = self.mb.procesar(mix)
                w0 = self._mb_wet
                if w0 != w1:
                    r = np.linspace(w0, w1, frames, dtype=np.float32)[:, None]
                    self._mb_wet = w1
                    mix = mix * (1.0 - r) + proc * r
                else:
                    mix = proc
                if w1 == 0.0:
                    self.mb.reset()
            except Exception:
                self.mb_activo = False
                self._mb_wet = 0.0
                import traceback; traceback.print_exc()
        try:
            mix = self.medios.procesar(mix)
        except Exception:
            self.medios.db = 0.0
            import traceback; traceback.print_exc()
        try:
            mix = self.agudos.procesar(mix)
        except Exception:
            self.agudos.db = 0.0
            import traceback; traceback.print_exc()
        try:
            mix = self.golpe.procesar(mix)
        except Exception:
            self.golpe.cantidad = 0.0
            import traceback; traceback.print_exc()
        mix = self.limitador.procesar(mix)
        try:
            self.nivel_vis = float(np.sqrt(np.mean(mix * mix)))
        except Exception:
            self.nivel_vis = 0.0
        pico = np.abs(mix)                       # red de seguridad (casi nunca actúa): recorte suave solo si algo se escapó
        if pico.size and float(pico.max()) > 0.98:
            mix = np.tanh(mix * 1.0).astype(np.float32) if float(pico.max()) > 1.5 else np.clip(mix, -0.99, 0.99)
        g0, g1 = self._gain_act, self.gain_obj
        if g0 != g1:
            mix = mix * np.linspace(g0, g1, frames, dtype=np.float32)[:, None]
            self._gain_act = g1
        elif g1 != 1.0:
            mix = mix * g1
        try:
            self.vu = (float(np.abs(mix[:, 0]).max()), float(np.abs(mix[:, 1]).max()), float(self.limitador.g), float(self._comp))
        except Exception:
            pass
        outdata[:] = mix.astype(np.float32)
        if self.grabador.activo:
            self.grabador.escribir(outdata)
