"""AutoMix — configuración guardada y formas de cruce."""
import json
import math
from setup.base import CACHE_DIR


# =====================================================================
# 3.7) FORMA DEL CRUCE
# =====================================================================
CONFIG_JSON = CACHE_DIR / "config_v2.json"      # configuración (incluye la forma del cruce)


try:
    _cfg_v1 = CACHE_DIR / "config.json"
    if not CONFIG_JSON.exists() and _cfg_v1.exists():
        import shutil as _sh
        _sh.copyfile(_cfg_v1, CONFIG_JSON)
except Exception:
    pass


DEF_PUNTO_A = 0.0      # valores por defecto de la forma de cruce


DEF_PUNTO_B = 0.15


CAIDA_A = 0.20         # por bandas: el que sale cae casi en picada, en este tramo de la mezcla a partir de A


UMBRAL_CAIDA = 0.30   # hasta este A el que sale baja con el arco completo; después se recorta


DEF_PUNTO_S = 0.5      # por bandas: en qué momento de la mezcla se traspasa el bajo (50 % = a la mitad)


DEF_MARCA = 0.50      # marca de auto-enganche: SIEMPRE visible (por defecto a la mitad del tema)




def perfil_cruce_ab(t, punto_a, punto_b):
    punto_a = max(0.0, min(0.97, punto_a))
    punto_b = max(0.0, min(0.97, punto_b))
    if t <= punto_a:
        vs = 1.0
    else:
        vs = math.cos(min(1.0, (t - punto_a) / (1.0 - punto_a)) * (math.pi / 2))
    if t <= punto_b:
        ve = 0.0
    else:
        ve = math.sin(min(1.0, (t - punto_b) / (1.0 - punto_b)) * (math.pi / 2))
    return vs, ve




def caida_a(pa):
    """Duración de la caída del que sale (por bandas). Hasta A=30 % es el arco de siempre (desde A hasta el final);
    pasado el 30 % se va recortando hasta caer casi en picada (a A=40 % dura CAIDA_A)."""
    if pa <= UMBRAL_CAIDA:
        return 1.0 - pa
    k = (pa - UMBRAL_CAIDA) / (0.40 - UMBRAL_CAIDA)
    return max(0.12, (1.0 - UMBRAL_CAIDA) + k * (CAIDA_A - (1.0 - UMBRAL_CAIDA)))




def perfil_cruce_bandas(t, punto_a, punto_b, punto_s, rampa=0.12, fin_a=None):
    """Cruce por bandas. Devuelve (sale_medios_agudos, entra_medios_agudos, sale_graves, entra_graves).
    · El entrante entra a nivel PLENO: en `punto_b` sube de 0 a 100 % en `rampa` de la mezcla (no se queda atenuado).
    · El que sale conserva sus medios/agudos hasta `punto_a` y ahí se va con un coseno.
    · El bajo es de uno solo a la vez: el del que sale se traspasa al del que entra en `punto_s` (el mezclador lo
      hace justo en la línea del compás)."""
    pa = max(0.0, min(0.97, punto_a)); pb = max(0.0, min(0.97, punto_b)); ps = max(0.0, min(0.97, punto_s))
    if fin_a is None:
        fa = pa + caida_a(pa)
    else:
        fa = fin_a
    fa = max(pa + 0.03, min(1.0, fa))                     # hasta dónde se va el que sale
    vs = 1.0 if t <= pa else math.cos(min(1.0, (t - pa) / (fa - pa)) * (math.pi / 2))
    r = max(0.02, min(rampa, 1.0 - pb))
    ve = 0.0 if t <= pb else math.sin(min(1.0, (t - pb) / r) * (math.pi / 2))
    lo_s = 1.0 if t < ps else 0.0
    lo_e = 0.0 if t < ps else 1.0
    return vs, ve, lo_s, lo_e




def leer_config():
    try:
        return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}




def guardar_config(**kw):
    try:
        cfg = leer_config(); cfg.update(kw)
        CONFIG_JSON.parent.mkdir(exist_ok=True)
        CONFIG_JSON.write_text(json.dumps(cfg), encoding="utf-8")
    except Exception as e:
        print("No se pudo guardar la configuración:", e)
