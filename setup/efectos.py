"""AutoMix — efectos de sonido para mezclar (sirena, bocina, láser, subida...). Se generan con numpy: no hace falta ningún archivo."""
import numpy as np
from scipy.signal import butter, sosfilt

# Cada efecto se normaliza a este nivel (RMS). El deslizador de efectos lo sube o baja desde ahí.
RMS_OBJETIVO = 0.11
PICO_MAX = 0.8


def _env(n, sr, ataque=0.008, relajo=0.02):
    e = np.ones(n)
    a = max(1, int(ataque * sr)); r = max(1, int(relajo * sr))
    e[:a] = np.linspace(0, 1, a); e[-r:] = np.minimum(e[-r:], np.linspace(1, 0, r))
    return e


def _ruido(n, rng):
    return rng.standard_normal(n)


def _filtro(x, tipo, fc, sr, orden=2):
    return sosfilt(butter(orden, fc, btype=tipo, fs=sr, output="sos"), x)


def _sirena(sr):
    n = int(2.4 * sr); t = np.arange(n) / sr
    f = 520 + 560 * (0.5 - 0.5 * np.cos(2 * np.pi * t / 0.8))            # sube y baja cada 0,8 s
    fase = 2 * np.pi * np.cumsum(f) / sr
    y = np.sin(fase) + 0.33 * np.sin(3 * fase) + 0.2 * np.sin(5 * fase)
    return y * _env(n, sr, 0.03, 0.35)


def _bocina(sr):
    partes = []
    for dur, pausa in ((0.28, 0.07), (0.28, 0.07), (0.85, 0.0)):
        n = int(dur * sr); t = np.arange(n) / sr
        y = np.zeros(n)
        for f in (415.3, 523.3, 622.3):                                     # acorde de bocina de aire
            fase = 2 * np.pi * f * t + 0.4 * np.sin(2 * np.pi * 6 * t)
            for k in range(1, 8):
                y += np.sin(k * fase) / k
        partes.append(y * _env(n, sr, 0.012, 0.06 if pausa else 0.25))
        partes.append(np.zeros(int(pausa * sr)))
    return np.concatenate(partes)


def _laser(sr):
    n = int(0.45 * sr); t = np.arange(n) / sr
    f = 3200 * np.exp(-t * 7.5) + 140
    fase = 2 * np.pi * np.cumsum(f) / sr
    y = np.sin(fase) + 0.4 * np.sin(2 * fase)
    return y * np.exp(-t * 3.0) * _env(n, sr, 0.002, 0.05)


def _subida(sr):
    rng = np.random.default_rng(3)
    n = int(3.2 * sr); t = np.arange(n) / sr; u = t / t[-1]
    ruido = _filtro(_ruido(n, rng), "high", 800, sr)
    # el ruido se va abriendo (más brillante) y más fuerte hacia el final
    ruido = ruido * (0.15 + 0.85 * u ** 2)
    f = 180 * (12.0 ** u)
    fase = 2 * np.pi * np.cumsum(f) / sr
    tono = 0.5 * np.sin(fase) * (0.2 + 0.8 * u)
    return (ruido * 0.55 + tono) * _env(n, sr, 0.05, 0.04)


def _impacto(sr):
    rng = np.random.default_rng(5)
    n = int(1.7 * sr); t = np.arange(n) / sr
    f = 32 + 90 * np.exp(-t * 14)
    fase = 2 * np.pi * np.cumsum(f) / sr
    bombo = np.sin(fase) * np.exp(-t * 2.6)
    golpe = _filtro(_ruido(n, rng), "low", 1800, sr) * np.exp(-t * 22) * 0.9
    return (bombo + golpe) * _env(n, sr, 0.001, 0.08)


def _caida(sr):
    rng = np.random.default_rng(7)
    n = int(1.6 * sr); t = np.arange(n) / sr; u = t / t[-1]
    f = 1800 * np.exp(-u * 3.2) + 70
    fase = 2 * np.pi * np.cumsum(f) / sr
    y = np.sin(fase) * 0.8 + _filtro(_ruido(n, rng), "low", 2500, sr) * 0.25
    return y * (1 - u) ** 1.5 * _env(n, sr, 0.005, 0.03)


def _redoble(sr):
    rng = np.random.default_rng(11)
    n = int(2.6 * sr); y = np.zeros(n)
    pos = 0.0; paso = 0.17
    golpe_base = _filtro(_ruido(int(0.12 * sr), rng), "high", 1200, sr) * np.exp(-np.arange(int(0.12 * sr)) / sr * 38)
    while pos < 2.3:
        i = int(pos * sr); g = (0.25 + 0.75 * pos / 2.3)
        seg = golpe_base[:max(0, min(len(golpe_base), n - i))]
        y[i:i + len(seg)] += seg * g
        pos += paso; paso = max(0.035, paso * 0.88)                        # cada vez más rápido
    i = int(2.35 * sr)                                                      # golpe final
    fin = _filtro(_ruido(n - i, rng), "high", 300, sr) * np.exp(-np.arange(n - i) / sr * 9)
    y[i:] += fin * 1.6
    return y * _env(n, sr, 0.002, 0.03)


EFECTOS = (
    ("🚨 Sirena", _sirena, "Sirena que sube y baja (2,4 s)"),
    ("📯 Bocina de aire", _bocina, "Bocina de DJ: dos toques cortos y uno largo (1,6 s)"),
    ("🔫 Láser", _laser, "Disparo láser descendente (0,5 s)"),
    ("🚀 Subida (riser)", _subida, "Barrido que va subiendo y se abre: para anunciar un drop (3,2 s)"),
    ("💥 Impacto", _impacto, "Golpe grave tipo explosión: para marcar el drop (1,7 s)"),
    ("⬇ Caída", _caida, "Barrido que baja y se apaga (1,6 s)"),
    ("🥁 Redoble", _redoble, "Redoble de caja que se acelera y cierra con un golpe (2,6 s)"),
)


def generar(indice, sr):
    """Devuelve el efecto como array estéreo float32 ya normalizado (sin pasarse de nivel)."""
    y = np.asarray(EFECTOS[indice][1](sr), dtype=np.float64)
    rms = float(np.sqrt(np.mean(y * y))) + 1e-9
    y = y * (RMS_OBJETIVO / rms)
    y = np.tanh(y / PICO_MAX) * PICO_MAX                                    # recorte suave: ningún pico se escapa
    return np.stack([y, y], axis=1).astype(np.float32)


class EfectoSalida:
    """Reproduce un efecto encima de la mezcla (lo suma antes del limitador)."""
    def __init__(self, sr):
        self.sr = sr
        self.buf = None
        self.pos = 0
        self.vol = 0.6                  # 0..1 (se aplica al cuadrado: 60 % queda unos 5 dB por debajo de la música, 100 % unos 3 dB por encima)
        self._cache = {}

    @property
    def ganancia(self):
        return float(self.vol) ** 2 * 2.6

    def lanzar(self, indice):
        b = self._cache.get(indice)
        if b is None:
            b = self._cache[indice] = generar(indice, self.sr)
        self.pos = 0
        self.buf = b

    def detener(self):
        self.buf = None

    @property
    def sonando(self):
        return self.buf is not None

    def sumar(self, mix):
        """Lo llama el callback de audio: suma el trozo que toca a `mix`."""
        b = self.buf
        if b is None:
            return mix
        n = len(mix); p = self.pos
        seg = b[p:p + n]
        if len(seg) == 0:
            self.buf = None
            return mix
        if len(seg) < n:
            seg = np.vstack([seg, np.zeros((n - len(seg), 2), dtype=np.float32)])
            self.buf = None
        else:
            self.pos = p + n
        return mix + seg * self.ganancia
