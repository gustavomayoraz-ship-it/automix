"""AutoMix — hilos (QThread) que analizan los temas sin trabar la interfaz."""
from pathlib import Path
import json
import os
import time
from PySide6.QtCore import QThread, Signal
from setup.analisis import BPM_MAX, BPM_MIN, _guardar_cache, _limpiar_grilla_cache, _pista_bpm, analizar_archivo
from setup.base import CACHE_DIR


_PRIORITARIOS = 0              # análisis de un deck esperando: la biblioteca le cede el turno




class Analyzer(QThread):
    done = Signal(str, dict)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        global _PRIORITARIOS
        _PRIORITARIOS += 1
        try:
            self._run()
        finally:
            _PRIORITARIOS = max(0, _PRIORITARIOS - 1)

    def _run(self):
        try:
            cache_key = CACHE_DIR / (Path(self.path).stem + ".json")
            if cache_key.exists():
                with open(cache_key) as f:
                    data = json.load(f)
                hint = _pista_bpm(self.path)
                dudoso = (data.get("ver", 1) < 3 and hint is not None
                          and abs(float(data.get("bpm", 0)) - hint) / hint > 0.06)
                if dudoso or (data.get("ver", 1) < 2 and not (BPM_MIN <= float(data.get("bpm", 0)) < BPM_MAX)):
                    result = analizar_archivo(self.path)          # BPM de otra octava (ej. 161 en vez de 80): se rehace una vez
                    _guardar_cache(cache_key, result)
                    self.done.emit(self.path, result)
                    return
                if data.get("grid") is None and data.get("ver", 1) < 4:
                    if _limpiar_grilla_cache(data):
                        data["ver"] = 4
                        _guardar_cache(cache_key, data)           # grilla regular lista: no se vuelve a calcular
                    else:
                        result = analizar_archivo(self.path)      # pulso irregular: se rehace una vez con la grilla del audio
                        _guardar_cache(cache_key, result)
                        self.done.emit(self.path, result)
                        return
                if "key" not in data or "voz" not in data:       # caché viejo sin tonalidad / voz: se completa una vez
                    try:
                        data.update(analizar_archivo(self.path, solo_clave=True))
                        _guardar_cache(cache_key, data)
                    except Exception:
                        import traceback; traceback.print_exc()
                self.done.emit(self.path, data)     # caché viejo sin auto_gain: lo calcula el deck del audio ya cargado
                return

            result = analizar_archivo(self.path)
            _guardar_cache(cache_key, result)
            self.done.emit(self.path, result)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.done.emit(self.path, {"error": str(e)})




class AnalizadorBiblioteca(QThread):
    progreso = Signal(int, int)
    tema_listo = Signal(str)
    terminado = Signal()

    def __init__(self, rutas, forzar=False):
        super().__init__()
        self.rutas = list(rutas)
        self.forzar = forzar
        self.cancelar = False

    def run(self):
        try:
            self._analizar_todo()
        except Exception:
            import traceback; traceback.print_exc()
        finally:
            self.terminado.emit()          # pase lo que pase, la lista se ordena con lo que haya

    def _analizar_todo(self):
        total = len(self.rutas)
        for i, ruta in enumerate(self.rutas, 1):
            if self.cancelar:
                break
            while _PRIORITARIOS > 0 and not self.cancelar:      # un deck está esperando su análisis: pasa primero
                time.sleep(0.2)
            try:
                cache_key = CACHE_DIR / (Path(ruta).stem + ".json")
                if self.forzar or not cache_key.exists():
                    t0 = time.monotonic()
                    result = analizar_archivo(ruta)
                    _guardar_cache(cache_key, result)
                    k = (result.get("key") or {}).get("camelot")
                    print(f"Analizado: {os.path.basename(ruta)} -> {result['bpm']:.1f} BPM, clave {k or '?'}")
                    if time.monotonic() - t0 > 60.0:
                        print(f"[análisis] ese tema tardó {time.monotonic() - t0:.0f} s")
                else:                                   # análisis viejo sin tonalidad: se completa solo la clave
                    with open(cache_key, encoding="utf-8") as f:
                        data = json.load(f)
                    if "key" not in data or "voz" not in data:
                        data.update(analizar_archivo(ruta, solo_clave=True))
                        _guardar_cache(cache_key, data)
                        print(f"Clave y voz: {os.path.basename(ruta)} -> {(data.get('key') or {}).get('camelot') or '?'}")
            except Exception:
                import traceback; traceback.print_exc()
            self.tema_listo.emit(ruta)
            self.progreso.emit(i, total)
