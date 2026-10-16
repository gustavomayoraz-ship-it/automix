"""AutoMix — constantes y ajustes generales de la interfaz."""


# =====================================================================
# 2) UTILIDADES Y ANÁLISIS
# =====================================================================
class _Ajustes:
    escala = 1.0          # escala actual de la interfaz (la cambia la ventana al redimensionarse)


AJ = _Ajustes()


ESC_MIN = 0.6         # escala más chica de la interfaz = ventana más chica posible


FUENTE_BOOST = 1.3     # multiplicador SOLO de las letras (1.0 = tamaño original); subilo/bajalo a gusto


SUPPORTED = (".mp3", ".wav", ".flac", ".ogg", ".m4a")



CF_BAJA_DESDE = 0.75


TARGET_LUFS_RMS = 0.15


NIVEL_V2 = 1.35          # V2: más fuerza general (+2,6 dB) sobre el AutoGain; el limitador por ganancia cuida los picos




def fmt_time(s):
    m, sec = divmod(int(s), 60)
    return f"{m:02d}:{sec:02d}"
