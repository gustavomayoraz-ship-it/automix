"""AutoMix — procesado de audio: multibanda, ecualizador inteligente, limitador."""
import math
import time
from scipy.signal import butter, sosfilt
import numpy as np


# =====================================================================
# 3.3) MULTIBANDA AUTOMÁTICA Y EQ INTELIGENTE
# =====================================================================
class MultibandaAuto:
    F_BAJOS, F_ALTOS = 150.0, 2500.0
    PERFIL = (
        (6.0, 1.8, 30.0, 200.0),
        (2.5, 2.5, 12.0, 120.0),
        (3.5, 2.8, 4.0, 70.0),
    )
    TAU_MEDIA_S = 4.0
    GATE_DB = -70.0
    K_EXCESO = (0.5, 0.5, 0.4)
    exceso = None

    def __init__(self, sr=44100):
        self.sr = sr
        self.intensidad = 0.6
        self.manual = False
        self.man_umbral = np.array([-18.0, -16.0, -14.0])
        self.man_ratio = np.array([2.0, 2.0, 2.0])
        self.man_comp = np.zeros(3)
        self._sos = {}
        self.set_cruces(self.F_BAJOS, self.F_ALTOS)
        self.reset()

    def set_cruces(self, f_bajos, f_altos):
        """Frecuencias de corte (Linkwitz-Riley de 4.º orden). Seguro de llamar en vivo."""
        sr = self.sr
        f_bajos = float(np.clip(f_bajos, 40.0, 1000.0))
        f_altos = float(np.clip(f_altos, f_bajos * 2.0, 12000.0))
        def lr4(tipo, fc):
            sos = butter(2, fc, btype=tipo, fs=sr, output="sos")
            return np.vstack([sos, sos])
        nuevo = {"lp1": lr4("low", f_bajos), "hp1": lr4("high", f_bajos),
                 "lp2": lr4("low", f_altos), "hp2": lr4("high", f_altos)}
        self._sos = nuevo
        self.f_bajos, self.f_altos = f_bajos, f_altos

    def reset(self):
        self._zi = {k: np.zeros((v.shape[0], 2, 2)) for k, v in self._sos.items()}
        self._e_lt = None
        self._t_med = 0.0
        self._g_db = np.zeros(3)
        self._mk = np.zeros(3)
        self.umbral = np.array([-18.0, -16.0, -14.0])
        self.ratio = np.ones(3)
        self.niveles = np.full(3, -90.0)
        self.reduccion = np.zeros(3)

    def _filtrar(self, clave, x):
        y, self._zi[clave] = sosfilt(self._sos[clave], x, axis=0, zi=self._zi[clave])
        return y

    def procesar(self, x):
        n = x.shape[0]
        dt = n / float(self.sr)
        xd = x.astype(np.float64)
        bajos = self._filtrar("lp1", xd)
        resto = self._filtrar("hp1", xd)
        medios = self._filtrar("lp2", resto)
        agudos = self._filtrar("hp2", resto)
        bandas = (bajos, medios, agudos)

        e = np.array([float(np.mean(b * b)) for b in bandas]) + 1e-14
        if self._e_lt is None or (float(self._e_lt.sum()) < 1e-6 and float(e.sum()) > 100.0 * float(self._e_lt.sum())):
            self._e_lt = e.copy()        # primer bloque, o la música arranca tras un silencio
            self._t_med = 0.0
        else:
            # al empezar, el promedio largo se arma como promedio acumulado (rápido) en vez de arrastrar 4 s
            tau = min(self.TAU_MEDIA_S, max(0.25, self._t_med))
            a = math.exp(-dt / tau)
            self._e_lt = a * self._e_lt + (1.0 - a) * e
        self._t_med += dt
        self.niveles = 10.0 * np.log10(self._e_lt)

        inten = float(np.clip(self.intensidad, 0.0, 1.0))
        out = np.zeros_like(xd)
        for i, b in enumerate(bandas):
            offset, rmax, ataque, relaj = self.PERFIL[i]
            g_prev = self._g_db[i]
            if self.manual:
                if self.niveles[i] < self.GATE_DB:
                    objetivo = 0.0
                else:
                    ratio = float(max(1.0, self.man_ratio[i])); umbral = float(self.man_umbral[i])
                    self.umbral[i], self.ratio[i], self._mk[i] = umbral, ratio, float(self.man_comp[i])
                    nivel_bloque = 20.0 * np.log10(float(np.max(np.abs(b))) + 1e-9)
                    sobre = max(0.0, nivel_bloque - umbral)
                    objetivo = -sobre * (1.0 - 1.0 / ratio) * inten + self._mk[i]   # Intensidad escala tu compresión (100% = tus valores)
            elif self.niveles[i] < self.GATE_DB or inten <= 0.0:
                objetivo = 0.0
                self._mk[i] += 0.1 * (0.0 - self._mk[i])
            else:
                ratio_obj = 1.0 + (rmax - 1.0) * inten
                off = offset
                if self.exceso is not None:
                    off -= self.K_EXCESO[i] * float(np.clip(self.exceso[i], 0.0, 8.0))
                thr_obj = float(np.clip(self.niveles[i] + off, -60.0, -3.0))
                self.umbral[i] += 0.12 * (thr_obj - self.umbral[i])
                self.ratio[i] += 0.12 * (ratio_obj - self.ratio[i])
                ratio, umbral = self.ratio[i], self.umbral[i]
                nivel_bloque = 20.0 * np.log10(float(np.max(np.abs(b))) + 1e-9)
                sobre = max(0.0, nivel_bloque - umbral)
                reduccion = sobre * (1.0 - 1.0 / ratio)
                mk_obj = float(np.clip(0.5 * max(0.0, 6.0 - off) * (1.0 - 1.0 / ratio), 0.0, 3.0))
                self._mk[i] += 0.12 * (mk_obj - self._mk[i])
                objetivo = -reduccion + self._mk[i]
            tc = ataque if objetivo < g_prev else relaj
            a = math.exp(-dt / (tc / 1000.0))
            g_new = a * g_prev + (1.0 - a) * objetivo
            self._g_db[i] = g_new
            rampa = np.linspace(10.0 ** (g_prev / 20.0), 10.0 ** (g_new / 20.0), n)[:, None]
            out += b * rampa
            self.reduccion[i] = max(0.0, -(g_new - self._mk[i]))
        return out.astype(np.float32)




class EQInteligente:
    BANDAS = (43, 63, 125, 250, 500, 1000, 2000, 4000, 8000)
    OBJETIVO = (0.0, 1.0, 3.0, 3.0, 1.5, 0.0, -2.0, -4.0, -7.0)
    MULT_LIMITE = np.array([3.0] + [1.0] * 8)
    TOPE_BANDA = np.array([20.0] + [15.0] * 8)
    PESO_PICO = np.array([0.35] + [1.0] * 8)
    NFFT, HOP = 8192, 4096
    TAU_LENTO, TAU_RAPIDO = 8.0, 1.5
    UMBRAL_CAMBIO_DB, TIEMPO_CAMBIO_SEG, SILENCIO_DB = 2.5, 1.0, -55.0
    # Al empezar un tema (todavía sin medición) se arranca con los graves más bajos y luego el
    # control automático los lleva al valor correcto. Bandas 43 / 63 / 125 Hz.
    ARRANQUE_DB = (-3.0, -2.0, -1.0)
    # Los graves casi nunca hay que subirlos mucho: en una intro pobre en graves el ecualizador los levantaba
    # +10 dB y cuando entraba el bajo pegaba un golpe enorme. Tope de subida (43 / 63 / 125 Hz) y subida lenta.
    SUBIDA_MAX_DB = (3.0, 3.0, 4.0)
    SUBIDA_LENTA = 0.2          # los graves suben a este factor de la velocidad con la que bajan

    def __init__(self, sr=44100):
        self.sr = sr
        self.fuerza = 0.6
        self.limite = 6.0
        self.velocidad = 2.0
        self.vent = np.hanning(self.NFFT)
        self.norma = float((self.vent.sum() / 2.0) ** 2)
        f = np.fft.rfftfreq(self.NFFT, 1.0 / sr)
        c = np.asarray(self.BANDAS, dtype=np.float64)
        medios = np.sqrt(c[:-1] * c[1:])
        bordes = np.concatenate(([c[0] ** 2 / medios[0]], medios, [c[-1] ** 2 / medios[-1]]))
        self.M = np.zeros((len(c), len(f)))
        for i in range(len(c)):
            idx = np.where((f >= bordes[i]) & (f < bordes[i + 1]))[0]
            if len(idx) == 0:
                idx = [int(np.argmin(np.abs(f - c[i])))]
            self.M[i, idx] = 1.0 / max(np.log2(bordes[i + 1] / bordes[i]), 0.2)
        self.reset()

    def reset(self):
        self.hist = np.zeros(self.NFFT)
        self._acum = 0
        self.Pl = self.Pr = None
        self.validas = 0.0
        self._exceso_t = 0.0
        self._silencio = 0.0
        self.t_cambio = -1e9
        self.auto = np.zeros(len(self.BANDAS))
        self.auto[:3] = self.ARRANQUE_DB
        self._arranque = True
        self._zi = np.zeros((len(self.BANDAS), 2, 2))
        self._sos_gains = None
        self._sos = None
        self._pre_db = 0.0

    @staticmethod
    def _forma(P):
        db = 10.0 * np.log10(np.asarray(P, dtype=np.float64) + 1e-12)
        return db - db.mean()

    def forma_lenta(self):
        if self.Pl is None or self.validas < 0.8:
            return None
        return self._forma(self.Pl)

    def exceso_grupos(self):
        forma = self.forma_lenta()
        if forma is None:
            return None
        meta = np.asarray(self.OBJETIVO) - np.mean(self.OBJETIVO)
        d = forma - meta
        return (float(np.mean(d[:3])), float(np.mean(d[3:7])), float(np.mean(d[7:])))

    def _alimentar(self, mono):
        n = len(mono)
        if n >= self.NFFT:
            self.hist[:] = mono[-self.NFFT:]
        else:
            self.hist = np.roll(self.hist, -n)
            self.hist[-n:] = mono
        self._acum += n
        if self._acum < self.HOP:
            return None
        dt = self._acum / float(self.sr)
        self._acum = 0
        rms = float(np.sqrt(np.mean(self.hist ** 2) + 1e-20))
        if 20.0 * np.log10(rms + 1e-12) < self.SILENCIO_DB:
            self._silencio += dt
            if self._silencio > 1.5:
                self.Pl = self.Pr = None; self.validas = 0.0
                self._arranque = True
                self.auto[:3] = np.minimum(self.auto[:3], self.ARRANQUE_DB)   # en silencio no se nota el salto
            return dt
        self._silencio = 0.0
        esp = np.abs(np.fft.rfft(self.hist * self.vent)) ** 2 / self.norma
        e = self.M @ esp + 1e-12
        if self.Pl is None:
            self.Pl, self.Pr = e.copy(), e.copy()
        else:
            # al empezar, el promedio "lento" es un promedio acumulado: así la medición sirve desde el primer segundo
            al = math.exp(-dt / min(self.TAU_LENTO, max(0.5, self.validas)))
            ar = math.exp(-dt / self.TAU_RAPIDO)
            self.Pl = al * self.Pl + (1.0 - al) * e
            self.Pr = ar * self.Pr + (1.0 - ar) * e
        self.validas += dt
        if self.validas > 3.0:
            desvio = float(np.sqrt(np.mean((self._forma(self.Pr) - self._forma(self.Pl)) ** 2)))
            if desvio > self.UMBRAL_CAMBIO_DB:
                self._exceso_t += dt
            else:
                self._exceso_t = max(0.0, self._exceso_t - dt)
            if self._exceso_t > self.TIEMPO_CAMBIO_SEG:
                self._exceso_t = 0.0
                self.t_cambio = time.monotonic()
                self.Pl = self.Pr = None; self.validas = 0.0
                self._arranque = True
        return dt

    def _controlar(self, dt):
        forma = self.forma_lenta()
        if forma is None:
            if self._arranque:        # sin medición todavía: bajar suave los graves hasta el valor de arranque
                obj = np.minimum(self.auto[:3], np.asarray(self.ARRANQUE_DB))
                self.auto[:3] += np.clip(obj - self.auto[:3], -2.0 * dt, 2.0 * dt)
            return
        self._arranque = False
        meta = np.asarray(self.OBJETIVO) - np.mean(self.OBJETIVO)
        lim = np.minimum(float(self.limite) * self.MULT_LIMITE, self.TOPE_BANDA)
        g = np.clip(self.fuerza * (meta - forma), -lim, lim)
        g[1:] -= g[1:].mean()
        g = np.clip(g, -lim, lim)
        vel = self.velocidad
        if time.monotonic() - self.t_cambio < 8.0:
            vel *= 2.0
        if self.validas < 6.0:             # recién empezó el tema: llegar rápido al valor correcto
            vel = max(vel, 8.0)
        g[:3] = np.minimum(g[:3], self.SUBIDA_MAX_DB)
        paso = vel * dt
        dif = g - self.auto
        sube = np.full(len(self.BANDAS), paso)
        sube[:3] = paso * self.SUBIDA_LENTA
        self.auto += np.clip(dif, -paso, sube)
        self.auto[:3] = np.minimum(self.auto[:3], self.SUBIDA_MAX_DB)

    def _calcular_sos(self, gains):
        sr = self.sr
        sos = np.zeros((len(self.BANDAS), 6))
        for i, (fc, g) in enumerate(zip(self.BANDAS, gains)):
            A = 10.0 ** (g / 40.0)
            if i < len(self.BANDAS) - 1:
                w0 = 2 * math.pi * fc / sr
                q = 0.9 if i == 0 else 1.1
                al = math.sin(w0) / (2 * q); cw = math.cos(w0)
                b0, b1, b2 = 1 + al * A, -2 * cw, 1 - al * A
                a0, a1, a2 = 1 + al / A, -2 * cw, 1 - al / A
            else:
                w0 = 2 * math.pi * 5700.0 / sr
                al = math.sin(w0) / (2 * 0.7); cw = math.cos(w0); be = 2 * math.sqrt(A) * al
                b0 = A * ((A + 1) + (A - 1) * cw + be)
                b1 = -2 * A * ((A - 1) + (A + 1) * cw)
                b2 = A * ((A + 1) + (A - 1) * cw - be)
                a0 = (A + 1) - (A - 1) * cw + be
                a1 = 2 * ((A - 1) - (A + 1) * cw)
                a2 = (A + 1) - (A - 1) * cw - be
            sos[i] = [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]
        return sos

    def procesar(self, x):
        n = x.shape[0]
        dt = self._alimentar(x.astype(np.float64).mean(axis=1))
        if dt is not None:
            self._controlar(dt)
        gains = np.round(self.auto, 2)
        gains = np.clip(gains, -15.0, 15.0)
        gains[0] = float(np.clip(self.auto[0], -20.0, 20.0))
        if self._sos is None or self._sos_gains is None or np.any(gains != self._sos_gains):
            self._sos = self._calcular_sos(gains)
            self._sos_gains = gains.copy()
        y, self._zi = sosfilt(self._sos, x.astype(np.float64), axis=0, zi=self._zi)
        pico = max(0.0, float(np.max(self.auto * self.PESO_PICO)))
        pre_obj = -0.5 * pico
        rampa = np.linspace(10.0 ** (self._pre_db / 20.0), 10.0 ** (pre_obj / 20.0), n)[:, None]
        self._pre_db = pre_obj
        return (y * rampa).astype(np.float32)




class _Seguidor:
    """Envolvente con ataque y relajación distintos (un valor cada PASO muestras). Mantiene estado."""
    def __init__(self, t_ataque, t_relaj, tasa):
        self.a_at = math.exp(-1.0 / max(t_ataque * tasa, 1e-6))
        self.a_re = math.exp(-1.0 / max(t_relaj * tasa, 1e-6))
        self.v = 0.0

    def seguir(self, valores):
        v, a_at, a_re = self.v, self.a_at, self.a_re
        out = [0.0] * len(valores)
        for i, x in enumerate(valores.tolist()):
            a = a_at if x > v else a_re
            v = a * v + (1.0 - a) * x
            out[i] = v
        self.v = v
        return np.asarray(out, dtype=np.float64)




class RealceGrave:
    """Golpe de bombo a 43 Hz (como en Ecualizador-DJ): trabaja sobre la banda 28-100 Hz y suma
       * un empujón fijo en la zona de 43 Hz,
       * un empujón extra solo en el ATAQUE de cada golpe (el "punch"),
       * armónicos suaves del bajo (~86 y 130 Hz) para que también se sienta en parlantes chicos.
    cantidad: 0..1 (0 = apagado)."""
    PASO = 16
    EMPUJE_FIJO_DB = 6.0
    EMPUJE_GOLPE_DB = 7.0
    MEZCLA_ARMONICOS = 0.55
    PISO = 10.0 ** (-60.0 / 20.0)

    def __init__(self, sr=44100):
        from scipy.signal import butter
        self.sr = sr
        self.cantidad = 0.0
        self._c_prev = 0.0
        self.sos_sub = np.vstack([butter(4, 28.0, "highpass", fs=sr, output="sos"),
                                  butter(6, 100.0, "lowpass", fs=sr, output="sos")])
        self.sos_arm = butter(4, [70.0, 260.0], "bandpass", fs=sr, output="sos")
        self.rapida = _Seguidor(0.002, 0.040, sr / float(self.PASO))
        self.lenta = _Seguidor(0.030, 0.300, sr / float(self.PASO))
        self.reset()

    def reset(self):
        self._zi_sub = np.zeros((len(self.sos_sub), 2, 2))
        self._zi_arm = np.zeros((len(self.sos_arm), 2, 2))
        self.rapida.v = 0.0; self.lenta.v = 0.0
        self._c_prev = self.cantidad

    def procesar(self, x):
        c1 = float(self.cantidad)
        c0 = self._c_prev
        if c1 <= 0.001 and c0 <= 0.001:
            self._c_prev = c1
            return x
        n = x.shape[0]
        xd = x.astype(np.float64)
        sub, self._zi_sub = sosfilt(self.sos_sub, xd, axis=0, zi=self._zi_sub)
        picos_m = np.abs(sub).max(axis=1)
        k = -(-n // self.PASO)
        if k * self.PASO != n:
            picos_m = np.pad(picos_m, (0, k * self.PASO - n), mode="edge")
        picos = picos_m.reshape(k, self.PASO).max(axis=1)
        rapida = self.rapida.seguir(picos)
        lenta = self.lenta.seguir(picos)
        sube_db = np.clip(20.0 * np.log10((rapida + 1e-5) / (lenta + 1e-5)), 0.0, 12.0)
        activo = np.clip((lenta - self.PISO) / self.PISO, 0.0, 1.0)
        cs = np.linspace(c0, c1, k)                       # la cantidad cambia suave dentro del bloque
        golpe = np.minimum(sube_db * 0.9, self.EMPUJE_GOLPE_DB) * activo * cs
        extra_lin = 10.0 ** ((self.EMPUJE_FIJO_DB * cs + golpe) / 20.0) - 1.0
        centros = (np.arange(k) + 0.5) * self.PASO
        g = np.interp(np.arange(n), centros, extra_lin)[:, None]
        arm, self._zi_arm = sosfilt(self.sos_arm, np.abs(sub), axis=0, zi=self._zi_arm)
        cn = np.linspace(c0, c1, n)[:, None]
        resto = 10.0 ** (-1.0 * cn / 20.0)                # hace lugar para que el bajo gane protagonismo
        self._c_prev = c1
        return (xd * resto + sub * g + arm * (self.MEZCLA_ARMONICOS * cn)).astype(np.float32)




class TonoMedios:
    """Campana ancha centrada en 1 kHz para bajar (o subir) los medios un poquito. 0 dB = no hace nada."""
    FC, Q = 1000.0, 0.6

    def __init__(self, sr=44100):
        self.sr = sr
        self.db = 0.0
        self._db_sos = None
        self._sos = None
        self._zi = np.zeros((1, 2, 2))

    def _calc(self, g):
        A = 10.0 ** (g / 40.0)
        w0 = 2 * math.pi * self.FC / self.sr
        al = math.sin(w0) / (2 * self.Q); cw = math.cos(w0)
        b0, b1, b2 = 1 + al * A, -2 * cw, 1 - al * A
        a0, a1, a2 = 1 + al / A, -2 * cw, 1 - al / A
        return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])

    def procesar(self, x):
        g = round(float(self.db), 2)
        if abs(g) < 0.05 and self._db_sos is None:
            return x
        if g != self._db_sos:
            self._sos = self._calc(g)
            self._db_sos = g if abs(g) >= 0.05 else None
            if self._db_sos is None:          # volvió a 0 dB: se deja de filtrar
                self._zi[:] = 0.0
                return x
        y, self._zi = sosfilt(self._sos, x.astype(np.float64), axis=0, zi=self._zi)
        return y.astype(np.float32)




class TonoAgudos:
    """Estante de agudos (desde ~6 kHz) para bajar o subir el brillo. 0 dB = no hace nada."""
    FC = 6000.0

    def __init__(self, sr=44100):
        self.sr = sr
        self.db = 0.0
        self._db_sos = None
        self._sos = None
        self._zi = np.zeros((1, 2, 2))

    def _calc(self, g):
        A = 10.0 ** (g / 40.0)
        w0 = 2 * math.pi * self.FC / self.sr
        cw = math.cos(w0)
        al = math.sin(w0) / 2.0 * math.sqrt(2.0)
        be = 2.0 * math.sqrt(A) * al
        b0 = A * ((A + 1) + (A - 1) * cw + be)
        b1 = -2 * A * ((A - 1) + (A + 1) * cw)
        b2 = A * ((A + 1) + (A - 1) * cw - be)
        a0 = (A + 1) - (A - 1) * cw + be
        a1 = 2 * ((A - 1) - (A + 1) * cw)
        a2 = (A + 1) - (A - 1) * cw - be
        return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])

    def procesar(self, x):
        g = round(float(self.db), 2)
        if abs(g) < 0.05 and self._db_sos is None:
            return x
        if g != self._db_sos:
            self._sos = self._calc(g)
            self._db_sos = g if abs(g) >= 0.05 else None
            if self._db_sos is None:
                self._zi[:] = 0.0
                return x
        y, self._zi = sosfilt(self._sos, x.astype(np.float64), axis=0, zi=self._zi)
        return y.astype(np.float32)




class AutoMejora:
    def __init__(self, sr=44100):
        self.eq = EQInteligente(sr)
        self.mb = MultibandaAuto(sr)

    @property
    def intensidad(self):
        return self.mb.intensidad

    @intensidad.setter
    def intensidad(self, v):
        self.mb.intensidad = v

    @property
    def niveles(self): return self.mb.niveles
    @property
    def reduccion(self): return self.mb.reduccion

    def reset(self):
        self.eq.reset(); self.mb.reset()

    def procesar(self, x):
        y = self.eq.procesar(x)                          # el EQ inteligente (Máx. corrección / Velocidad) sigue activo también en manual
        self.mb.exceso = None if self.mb.manual else self.eq.exceso_grupos()
        return self.mb.procesar(y)




# =====================================================================
# 3.5) MIXER GLOBAL
# =====================================================================
class CruceLR4:
    """Cruce Linkwitz-Riley de 4.º orden estéreo, con estado entre bloques. graves + resto = pasa-todo:
    con las dos ganancias en 1 el sonido es idéntico al original (sin hueco ni refuerzo)."""
    def __init__(self, fc, sr):
        from scipy.signal import butter
        self.sl = butter(2, fc, "low", fs=sr, output="sos")
        self.sh = butter(2, fc, "high", fs=sr, output="sos")
        self.reset()

    def reset(self):
        n = self.sl.shape[0]
        self.z = [np.zeros((n, 2, 2)) for _ in range(4)]

    def split(self, x):
        from scipy.signal import sosfilt
        l1, self.z[0] = sosfilt(self.sl, x, axis=0, zi=self.z[0])
        lo, self.z[1] = sosfilt(self.sl, l1, axis=0, zi=self.z[1])
        h1, self.z[2] = sosfilt(self.sh, x, axis=0, zi=self.z[2])
        hi, self.z[3] = sosfilt(self.sh, h1, axis=0, zi=self.z[3])
        return lo.astype(np.float32), hi.astype(np.float32)




class LimitadorSuave:
    """Limitador por GANANCIA (no recorta la onda): baja el volumen de todo el bloque de forma suave justo antes
    de un pico y lo devuelve despacio. Así los graves fuertes no se deforman (un recorte por muestra sobre un
    bajo de 50 Hz mete armónicos y suena a 'crunch')."""
    TECHO = 0.95
    CHUNK = 32
    ADELANTO = 3            # trozos de adelanto dentro del bloque (~2 ms): la bajada empieza antes del pico
    LIBERA_S = 0.120

    def __init__(self, sr=44100):
        self.sr = sr
        self.g = 1.0
        self._sube = self.CHUNK / (self.LIBERA_S * sr)      # cuánto puede subir la ganancia por trozo

    def procesar(self, x):
        n = x.shape[0]
        if n == 0:
            return x
        C = self.CHUNK
        k = -(-n // C)
        pico = np.abs(x).max(axis=1)
        if k * C != n:
            pico = np.pad(pico, (0, k * C - n))
        pico = pico.reshape(k, C).max(axis=1)
        necesaria = np.minimum(1.0, self.TECHO / np.maximum(pico, 1e-9))
        if float(necesaria.min()) >= 1.0 and self.g >= 0.9999:
            self.g = 1.0
            return x
        ad = self.ADELANTO
        pad = np.concatenate([necesaria, np.ones(ad)])
        obj = pad[0:k].copy()
        for j in range(1, ad + 1):
            obj = np.minimum(obj, pad[j:j + k])           # la bajada anticipa el pico
        gk = np.empty(k)
        g = self.g
        for i in range(k):
            g = obj[i] if obj[i] < g else min(obj[i], g + self._sube)
            gk[i] = g
        self.g = g
        # ganancia por muestra: interpolación entre los centros de los trozos (sin saltos)
        cen = np.arange(k) * C + C * 0.5
        gm = np.interp(np.arange(n), cen, gk).astype(np.float32)
        # la interpolación puede quedar apenas sobre el objetivo entre trozos: se toma el mínimo con el trozo propio
        gm = np.minimum(gm, np.repeat(obj, C)[:n].astype(np.float32) + 0.02)
        return x * gm[:, None]
