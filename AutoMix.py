"""
AutoMix Pro — PySide6
- Play individual por deck
- Waveform de cada deck se mueve SOLO si suena
- 🔗 Sync automático de BPM y downbeats sin tirones
- 🔊 Sistema Automático de Ganancia (Auto-Gain RMS normalizado a -14 dBFS)
- 🎚️ Crossfader: volumen A↔B + BPM compartido interpolado
- 🎬 Mezclar: auto-fade con duración configurable (atajo F2) + pausa 3 s al 50 %
- ⚓ Barra de progreso con marca de auto-enganche
- ⏯ Tecla Espacio para pausar/reanudar el deck sonando
- ⟲ Botón de reset de tiempo en cada deck
- 🛑 Auto-stop del deck silenciado al llegar los extremos
- ✋ Manito: arrastrar la waveform
- Playhead fijo al centro
- Tempo suavizado y biblioteca ordenada por BPM
"""

import sys
import os
import re
import json
import math
import time
import threading
from pathlib import Path

# =====================================================================
# 1) DEPENDENCIAS DESDE ./dependencias_offline
# =====================================================================
ROOT = Path(__file__).parent.resolve()
OFFLINE = ROOT / "dependencias_offline"
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)

try:                                  # el proceso hijo del análisis deja sus errores en cache/hijo.log
    import multiprocessing as _mp0
    if _mp0.current_process().name != "MainProcess":      # (parent_process() sigue en None mientras el hijo importa este archivo)
        import faulthandler
        _f_hijo = open(CACHE_DIR / "hijo.log", "a", encoding="utf-8", buffering=1)
        sys.stderr = _f_hijo
        faulthandler.enable(file=_f_hijo)
except Exception:
    pass

# (módulo, paquete de pip): si falta alguno dentro de ./dependencias_offline se descarga ahí al abrir el programa
DEPENDENCIAS = [("numpy", "numpy"), ("scipy", "scipy"), ("soundfile", "soundfile"),
                ("sounddevice", "sounddevice"), ("librosa", "librosa"), ("PySide6", "PySide6-Essentials")]   # Essentials: solo Widgets/Core/Gui (~400 MB menos)


def _modulo_en_offline(mod):
    try:
        return (OFFLINE / mod).is_dir() or any(OFFLINE.glob(mod + ".*")) or (OFFLINE / (mod + ".py")).exists()
    except Exception:
        return False


def _instalar_en_offline(pq):
    """Descarga/instala un paquete (con sus dependencias) dentro de ./dependencias_offline.
    Devuelve (ok, detalle)."""
    import subprocess
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            exe = cand
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}      # CREATE_NO_WINDOW
    try:
        OFFLINE.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([exe, "-m", "pip", "install", "--target", str(OFFLINE),
                            "--disable-pip-version-check", pq],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)
        ok = (r.returncode == 0)
        det = None if ok else (r.stderr or r.stdout or "pip no devolvió detalle.").strip()
    except Exception as e:
        ok, det = False, str(e)
    try:
        with open(CACHE_DIR / "dependencias.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + pq + "  " + ("OK" if ok else "ERROR\n" + str(det)) + "\n")
    except Exception:
        pass
    return ok, det


def asegurar_dependencias():
    """Ventana (tkinter, igual a la del reproductor anterior) que verifica las dependencias dentro de
    ./dependencias_offline y descarga ahí las que falten. Solo corre en el proceso principal."""
    try:
        import multiprocessing as _mp1
        if _mp1.current_process().name != "MainProcess":      # proceso hijo del análisis: nada de ventanas
            return
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except Exception:                                  # sin tkinter: descarga igual, sin ventana
        for m, pq in DEPENDENCIAS:
            if not _modulo_en_offline(m):
                _instalar_en_offline(pq)
        return
    import threading, queue
    cola = queue.Queue()
    errores = {}

    class Ventana(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("🔍 Verificación de dependencias")
            self.resizable(False, False)
            self.configure(bg="#f8f9fa")
            self.attributes("-topmost", True)
            self.estados = {}
            self.cerrado = False
            cont = tk.Frame(self, bg="#f8f9fa", padx=20, pady=15)
            cont.pack(fill="both", expand=True)
            tk.Label(cont, text="📦 Verificando dependencias", font=("Segoe UI", 14, "bold"),
                     bg="#f8f9fa", fg="#2c3e50").pack(anchor="w")
            tk.Label(cont, text="Se guardan en la carpeta dependencias_offline", font=("Segoe UI", 9),
                     bg="#f8f9fa", fg="#7f8c8d").pack(anchor="w", pady=(0, 12))
            for _mod, nombre in DEPENDENCIAS:
                fila = tk.Frame(cont, bg="#f8f9fa")
                fila.pack(fill="x", pady=2)
                tk.Label(fila, text=nombre, font=("Segoe UI", 9, "bold"), bg="#f8f9fa", fg="#2c3e50",
                         width=14, anchor="w").pack(side="left")
                lbl = tk.Label(fila, text="⏳ Pendiente", font=("Segoe UI", 9), bg="#f8f9fa",
                               fg="#7f8c8d", anchor="w")
                lbl.pack(side="left", fill="x", expand=True)
                lbl.bind("<Button-1>", lambda e, n=nombre: self._detalle(n))
                self.estados[nombre] = lbl
            self.barra = ttk.Progressbar(cont, mode="determinate", length=380)
            self.barra.pack(fill="x", pady=(10, 6))
            self.general = tk.Label(cont, text="🔍 Iniciando verificación...", font=("Segoe UI", 9),
                                    bg="#f8f9fa", fg="#2c3e50", anchor="w", justify="left", wraplength=360)
            self.general.pack(fill="x", pady=(0, 4))
            self.btn = tk.Button(cont, text="🔄 Reintentar", font=("Segoe UI", 9, "bold"), bg="#2ecc71",
                                 fg="white", relief="flat", padx=10, pady=6, command=self._reintentar)
            self.update_idletasks()
            w, h = 420, self.winfo_reqheight() + 16
            self.geometry("%dx%d+%d+%d" % (w, h, (self.winfo_screenwidth() - w) // 2,
                                           (self.winfo_screenheight() - h) // 2))
            self.protocol("WM_DELETE_WINDOW", self._cerrar)
            self.after(60, self._leer)
            self._lanzar()

        def _detalle(self, n):
            if errores.get(n):
                messagebox.showerror("Error instalando '%s'" % n, errores[n])

        def _lanzar(self):
            threading.Thread(target=self._trabajo, daemon=True).start()

        def _trabajo(self):
            total = len(DEPENDENCIAS)
            hubo = False
            for i, (mod, pq) in enumerate(DEPENDENCIAS):
                cola.put(("gen", "🔍 Verificando %s..." % pq))
                if _modulo_en_offline(mod):
                    cola.put(("est", pq, "✅ Instalado", "#27ae60"))
                else:
                    cola.put(("est", pq, "⬇️ Descargando...", "#e67e22"))
                    cola.put(("gen", "⬇️ Descargando %s a dependencias_offline (puede tardar unos minutos)..." % pq))
                    ok, det = _instalar_en_offline(pq)
                    if ok and _modulo_en_offline(mod):
                        cola.put(("est", pq, "✅ Descargado", "#27ae60"))
                    else:
                        hubo = True
                        errores[pq] = det or "El paquete se instaló pero no aparece en dependencias_offline."
                        cola.put(("est", pq, "❌ Error -- click acá para ver el detalle", "#e74c3c"))
                cola.put(("bar", (i + 1) / total * 100))
            cola.put(("fin", hubo))

        def _leer(self):
            try:
                while True:
                    m = cola.get_nowait()
                    if m[0] == "est":
                        self.estados[m[1]].config(text=m[2], fg=m[3])
                    elif m[0] == "gen":
                        self.general.config(text=m[1], fg="#2c3e50")
                    elif m[0] == "bar":
                        self.barra["value"] = m[1]
                    elif m[0] == "fin":
                        if m[1]:
                            self.general.config(text="⚠️ Alguna dependencia no se pudo descargar -- hacé click "
                                                "en su estado para ver el motivo, solucionalo y reintentá.",
                                                fg="#e74c3c")
                            self.btn.pack(pady=(0, 4))
                            self.update_idletasks()
                            self.geometry("420x%d" % (self.winfo_reqheight() + 16))
                        else:
                            self.general.config(text="✅ Todo listo, iniciando...", fg="#2c3e50")
                            self.after(500, self.destroy)
                        return self.after(60, self._leer) if m[1] else None
            except queue.Empty:
                pass
            self.after(60, self._leer)

        def _reintentar(self):
            self.btn.pack_forget()
            errores.clear()
            for lbl in self.estados.values():
                lbl.config(text="⏳ Pendiente", fg="#7f8c8d")
            self.barra["value"] = 0
            self._lanzar()

        def _cerrar(self):
            self.cerrado = True
            self.destroy()

    v = Ventana()
    v.mainloop()
    if v.cerrado:
        sys.exit(0)


# =====================================================================
# 1.5) CONSOLA OCULTA (con botón 🖥 para verla cuando haga falta)
# =====================================================================
class ConsolaOculta:
    """Oculta la ventana negra de consola (al abrir el .py con doble clic) pero sigue guardando todo lo
    que el programa imprime (con hora). El botón 🖥 de la ventana la abre/cierra: al abrirla muestra el
    historial. Además deja el registro en cache/consola.log y los cierres bruscos en cache/crash.log."""
    MAX_LINEAS = 4000

    def __init__(self):
        from collections import deque
        self.buffer = deque(maxlen=self.MAX_LINEAS)
        self.visible = False
        self._destino = None            # stream de la consola cuando está visible
        self._orig = {}
        self._inicio_linea = True
        self._archivo = None
        self.es_windows = (os.name == "nt")
        self._propia = False            # la consola es de este proceso: no se vuelca a ella mientras está oculta
        self._modo = None               # None | "libre" (consola propia, FreeConsole) | "ventana" (la comparte py.exe) | "terminal"
        self._hwnd = 0

    # ---- captura de stdout/stderr ----
    def instalar(self):
        try:
            log = CACHE_DIR / "consola.log"
            if log.exists() and log.stat().st_size > 2_000_000:
                log.write_text("", encoding="utf-8")
            self._archivo = open(log, "a", encoding="utf-8", buffering=1)
        except Exception:
            self._archivo = None
        try:
            import faulthandler
            self._crash = open(CACHE_DIR / "crash.log", "a", buffering=1)
            faulthandler.enable(self._crash)
        except Exception:
            pass
        for nombre in ("stdout", "stderr"):
            self._orig[nombre] = getattr(sys, nombre, None)
            setattr(sys, nombre, _TeeConsola(self, nombre))
        if self.es_windows:
            try:
                self._detectar_consola()
            except Exception:
                pass

    @staticmethod
    def _nombre_proceso(pid):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520); n = wintypes.DWORD(520)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return os.path.basename(buf.value).lower()
        finally:
            k32.CloseHandle(h)
        return ""

    def _detectar_consola(self):
        import ctypes
        k32 = ctypes.windll.kernel32; u32 = ctypes.windll.user32
        hwnd = k32.GetConsoleWindow()
        if not hwnd:
            return
        lista = (ctypes.c_uint * 32)()
        n = k32.GetConsoleProcessList(lista, 32)
        otros = [int(lista[i]) for i in range(min(n, 32)) if int(lista[i]) != os.getpid()]
        raiz = u32.GetAncestor(hwnd, 3) or hwnd           # con Windows Terminal, la ventana real es la "dueña"
        if not otros:
            self._modo = "libre"; self._propia = True
            k32.FreeConsole()
        elif all(self._nombre_proceso(p) in ("py.exe", "pyw.exe") for p in otros):
            # abierto con doble clic vía el lanzador py.exe: la consola es compartida, no se puede soltar; se esconde la ventana
            self._modo = "ventana"; self._propia = False; self._hwnd = raiz
            u32.ShowWindow(raiz, 0)
        else:
            self._modo = "terminal"                       # lanzado desde una terminal tuya: no se la toca

    def escribir(self, nombre, texto):
        if not texto:
            return
        import datetime
        salida = []
        for ch in texto:
            if self._inicio_linea and ch not in "\r\n":
                salida.append(datetime.datetime.now().strftime("[%H:%M:%S] "))
                self._inicio_linea = False
            salida.append(ch)
            if ch == "\n":
                self._inicio_linea = True
        t = "".join(salida)
        self.buffer.append(t)
        if self._archivo:
            try: self._archivo.write(t)
            except Exception: pass
        if self.visible and self._destino:
            try:
                self._destino.write(t); self._destino.flush()
            except Exception:
                pass
        else:
            o = self._orig.get(nombre)
            if o is not None and not self._propia:
                try: o.write(texto); o.flush()
                except Exception: pass

    # ---- abrir / cerrar ----
    def mostrar(self):
        if not self.es_windows or self.visible:
            return self.visible
        if self._modo == "ventana":
            try:
                import ctypes
                u32 = ctypes.windll.user32
                try:
                    hmenu = u32.GetSystemMenu(self._hwnd, False)
                    u32.DeleteMenu(hmenu, 0xF060, 0)
                    ctypes.windll.kernel32.SetConsoleCtrlHandler(None, True)
                except Exception:
                    pass
                u32.ShowWindow(self._hwnd, 5)
                self.visible = True
            except Exception:
                self.visible = False
            return self.visible
        if self._modo == "terminal":
            return False
        try:
            import ctypes
            k32 = ctypes.windll.kernel32; u32 = ctypes.windll.user32
            if not k32.GetConsoleWindow():
                k32.AllocConsole()
            hwnd = k32.GetConsoleWindow()
            k32.SetConsoleOutputCP(65001)
            k32.SetConsoleTitleW("AutoMix — consola (se cierra con el botón 🖥, no con la X)")
            try:
                k32.SetConsoleCtrlHandler(None, True)         # Ctrl+C acá no cierra el programa
                hmenu = u32.GetSystemMenu(hwnd, False)
                u32.DeleteMenu(hmenu, 0xF060, 0)               # sin botón X: cerrarla mataría el programa
            except Exception:
                pass
            if hwnd:
                u32.ShowWindow(hwnd, 5)
            self._destino = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
            self._destino.write("".join(self.buffer))
            self._destino.flush()
            self.visible = True
        except Exception:
            self.visible = False
        return self.visible

    def ocultar(self):
        if not self.es_windows or not self.visible:
            return
        if self._modo == "ventana":
            try:
                import ctypes
                ctypes.windll.user32.ShowWindow(self._hwnd, 0)
            except Exception:
                pass
            self.visible = False
            return
        try:
            import ctypes
            try:
                if self._destino: self._destino.close()
            except Exception:
                pass
            self._destino = None
            self.visible = False
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass

    def alternar(self):
        if self.visible: self.ocultar()
        else: self.mostrar()
        return self.visible


class _TeeConsola:
    def __init__(self, consola, nombre):
        self._c = consola; self._n = nombre

    def write(self, texto):
        try: self._c.escribir(self._n, texto)
        except Exception: pass
        return len(texto) if texto else 0

    def flush(self):
        pass

    def isatty(self):
        return False

    def __getattr__(self, nombre):
        o = self._c._orig.get(self._n)
        if o is None: raise AttributeError(nombre)
        return getattr(o, nombre)


CONSOLA = ConsolaOculta()
try:
    import multiprocessing as _mp
    if _mp.parent_process() is None:          # el proceso hijo del análisis no toca la consola
        CONSOLA.instalar()
except Exception:
    pass

# La consola ya está oculta: recién ahora se verifican/descargan las dependencias (ventana tkinter)
asegurar_dependencias()

if OFFLINE.exists():
    sys.path.insert(0, str(OFFLINE))
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(OFFLINE))
        except Exception:
            pass
    os.environ["PATH"] = str(OFFLINE) + os.pathsep + os.environ.get("PATH", "")

import numpy as np
import soundfile as sf
import sounddevice as sd
import librosa
from scipy.signal import butter, sosfilt

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QFileDialog, QGroupBox,
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsPolygonItem,
    QGraphicsSimpleTextItem, QFrame, QSplitter, QListWidget, QListWidgetItem,
    QLineEdit, QAbstractItemView, QSpinBox, QDialog, QCheckBox, QSizePolicy,
    QLayout, QScrollBar, QAbstractScrollArea, QProgressBar, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPointF, QMimeData, QUrl, QSize, QRectF
from PySide6.QtGui import (
    QGuiApplication, QDragEnterEvent, QDropEvent, QColor, QPen, QPainter, QBrush,
    QPolygonF, QFont, QCursor, QKeyEvent, QShortcut, QKeySequence
)


# =====================================================================
# 2) UTILIDADES Y ANÁLISIS
# =====================================================================
UI_ESCALA = 1.0
SUPPORTED = (".mp3", ".wav", ".flac", ".ogg", ".m4a")

CF_BAJA_DESDE = 0.75
TARGET_LUFS_RMS = 0.15


def fmt_time(s):
    m, sec = divmod(int(s), 60)
    return f"{m:02d}:{sec:02d}"


def lowpass_kick(y, sr, cutoff=150.0, order=4):
    sos = butter(order, cutoff, btype="low", fs=sr, output="sos")
    return sosfilt(sos, y)


def refine_onsets_to_peak(onset_env, onsets_frames, hop, sr, win_frames=3):
    refined = []
    n = len(onset_env)
    for f in onsets_frames:
        a = max(0, f - win_frames)
        b = min(n, f + win_frames + 1)
        if b <= a:
            continue
        local = onset_env[a:b]
        peak_off = int(np.argmax(local))
        peak_frame = a + peak_off
        if 0 < peak_frame < n - 1:
            y1 = onset_env[peak_frame - 1]
            y2 = onset_env[peak_frame]
            y3 = onset_env[peak_frame + 1]
            denom = (y1 - 2 * y2 + y3)
            if abs(denom) > 1e-12:
                delta = 0.5 * (y1 - y3) / denom
                delta = float(np.clip(delta, -0.5, 0.5))
            else:
                delta = 0.0
        else:
            delta = 0.0
        t = (peak_frame + delta) * hop / sr
        refined.append(t)
    return np.array(refined, dtype=float)


def detect_kicks(y, sr):
    y_low = lowpass_kick(y, sr, cutoff=150.0, order=4)
    hop = 256
    env = librosa.onset.onset_strength(y=y_low, sr=sr, hop_length=hop,
                                       aggregate=np.median)
    onsets_frames = librosa.onset.onset_detect(
        onset_envelope=env, sr=sr, hop_length=hop,
        backtrack=False, units="frames",
        pre_max=3, post_max=3, pre_avg=3, post_avg=3, delta=0.15, wait=3
    )
    return refine_onsets_to_peak(env, onsets_frames, hop, sr)


def detect_beats(y, sr):
    hop = 512
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop, units="frames")
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    beats = refine_onsets_to_peak(env, beat_frames, hop, sr)
    return float(tempo) if np.isscalar(tempo) else float(tempo[0]), beats


def detect_downbeats(y, sr, beats):
    if len(beats) < 4:
        return beats
    y_low = lowpass_kick(y, sr, cutoff=150.0)
    win = int(0.06 * sr)
    energies = []
    for b in beats:
        c = int(b * sr)
        a = max(0, c - win)
        z = min(len(y_low), c + win)
        if z > a:
            energies.append(float(np.mean(np.abs(y_low[a:z]))))
        else:
            energies.append(0.0)
    energies = np.array(energies)
    best_off, best_score = 0, -1.0
    for off in range(4):
        idx = np.arange(off, len(beats), 4)
        if len(idx) == 0:
            continue
        score = float(energies[idx].mean())
        if score > best_score:
            best_score, best_off = score, off
    return beats[best_off::4]


_LOCK_ANALISIS = threading.Lock()     # librosa/numba no tolera dos análisis a la vez (cierra el programa)
_HILOS_VIVOS = set()                  # un QThread NO puede destruirse mientras corre (Qt aborta el programa)


def _mantener_vivo(hilo):
    _HILOS_VIVOS.add(hilo)
    hilo.finished.connect(lambda h=hilo: _HILOS_VIVOS.discard(h))


_POOL = None
_POOL_BLOQ_HASTA = 0.0         # si el proceso aparte falla o se cuelga, un rato se analiza en el programa mismo
TIMEOUT_ANALISIS = 150.0       # un tema normal tarda unos 5-10 s; pasado esto se lo da por colgado
_PRIORITARIOS = 0              # análisis de un deck esperando: la biblioteca le cede el turno
_POOL_USOS = 0                 # el proceso aparte se renueva cada tanto (un hijo de larga vida puede ir engordando)
POOL_RENOVAR_CADA = 12


def _cerrar_pool():
    global _POOL
    p, _POOL = _POOL, None
    if p is None:
        return
    try:
        procs = list((getattr(p, "_processes", None) or {}).values())
    except Exception:
        procs = []
    try:
        p.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    for pr in procs:                     # shutdown no mata a un hijo colgado
        try:
            pr.kill()
        except Exception:
            pass


def analizar_archivo(path):
    """El análisis (librosa/numba) retiene el GIL por momentos y trababa el audio ('rrrr').
    Se hace en un proceso aparte; si eso falla o se cuelga, se hace acá como antes."""
    global _POOL, _POOL_BLOQ_HASTA, _POOL_USOS
    with _LOCK_ANALISIS:
        if time.monotonic() >= _POOL_BLOQ_HASTA:
            try:
                if _POOL is None:
                    from concurrent.futures import ProcessPoolExecutor
                    import multiprocessing
                    ctx = multiprocessing.get_context("spawn")
                    pw = Path(sys.executable).with_name("pythonw.exe")      # el hijo no abre ventana negra
                    if os.name == "nt" and pw.exists():
                        ctx.set_executable(str(pw))
                    _POOL = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
                res = _POOL.submit(_analizar_archivo, path).result(timeout=TIMEOUT_ANALISIS)
                _POOL_USOS += 1
                if _POOL_USOS >= POOL_RENOVAR_CADA:
                    _POOL_USOS = 0
                    _cerrar_pool()
                return res
            except Exception as e:
                from concurrent.futures import TimeoutError as _TO
                from concurrent.futures.process import BrokenProcessPool
                _cerrar_pool()
                _POOL_USOS = 0
                if isinstance(e, (_TO, BrokenProcessPool, OSError)):
                    _POOL_BLOQ_HASTA = time.monotonic() + 600.0
                    print(f"[análisis] el proceso aparte falló ({type(e).__name__}); se analiza en el programa durante unos minutos")
        return _analizar_archivo(path)


def _pista_bpm(path):
    """BPM que ya trae el nombre del archivo, ej. '[82 BPM] Te conozco.mp3' (None si no tiene)."""
    m = re.search(r"\[\s*(\d{2,3}(?:[.,]\d+)?)\s*BPM\s*\]", os.path.basename(str(path)), re.I)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return v if 50.0 <= v <= 220.0 else None


def _bpm_de_grilla(beats):
    """BPM preciso = 60 / media de los intervalos entre beats (sin los atípicos)."""
    b = np.asarray(beats, dtype=np.float64)
    if len(b) < 16:
        return None
    iv = np.diff(b)
    m = float(np.median(iv))
    if m <= 0:
        return None
    k = iv[np.abs(iv - m) < 0.08 * m]
    if len(k) < 12:
        return None
    return 60.0 / float(np.mean(k))


def detect_beats_con_pista(y, sr, hint):
    hop = 512
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    _, frames = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop,
                                        start_bpm=float(hint), tightness=100, units="frames")
    return refine_onsets_to_peak(env, frames, hop, sr)


BPM_MIN, BPM_MAX = 70.0, 150.0     # rango musical: fuera de él, librosa suele equivocarse por una octava (82 -> 164)


def _plegar_tempo(tempo, beats, y, sr):
    """Si el tempo cae fuera de [70, 150) es casi seguro un error de octava (el doble o la mitad).
    Se lleva al rango y se corrige también la grilla de beats (se queda con la mitad de los golpes, los
    de más energía grave, o se agregan los intermedios), para que los downbeats sigan siendo cada 4 golpes."""
    beats = np.asarray(beats, dtype=np.float64)
    tempo = float(tempo)
    for _ in range(2):
        if tempo >= BPM_MAX and len(beats) >= 8:
            y_low = lowpass_kick(y, sr, cutoff=150.0)
            win = int(0.05 * sr)

            def energia(bs):
                v = []
                for b in bs:
                    c = int(b * sr); a = max(0, c - win); z = min(len(y_low), c + win)
                    if z > a: v.append(float(np.mean(np.abs(y_low[a:z]))))
                return float(np.mean(v)) if v else 0.0
            fase = 0 if energia(beats[0::2]) >= energia(beats[1::2]) else 1
            beats = beats[fase::2]
            tempo /= 2.0
        elif 0 < tempo < BPM_MIN and len(beats) >= 8:
            medios = (beats[:-1] + beats[1:]) / 2.0
            beats = np.sort(np.concatenate([beats, medios]))
            tempo *= 2.0
    return tempo, beats



# ---------------------------------------------------------------------
# Grilla de pulso regular. El tracker de beats de librosa suele "perder" el pulso en tramos largos
# (se corre media pulsación o una entera, o deriva y se re-engancha de golpe) y los downbeats heredan el
# error: por eso las marcas del timeline quedaban irregulares y el sync no podía coincidir. Los temas de
# estudio tienen tempo fijo, así que se ajusta UNA línea de pulso para todo el tema y se usa tanto para
# dibujar como para sincronizar.
# ---------------------------------------------------------------------
def _linea_de_beats(beats):
    """Línea (intercepto, período) que mejor explica la mayoría de los beats detectados, o None."""
    b = np.asarray(beats, dtype=np.float64)
    if len(b) < 24:
        return None
    p0 = float(np.median(np.diff(b)))
    if not (0.25 < p0 < 1.5):
        return None
    phi = np.mod(b - b[0], p0)
    nb = max(8, int(p0 / 0.01))
    h, _ = np.histogram(phi, bins=nb, range=(0, p0))
    h = np.convolve(np.r_[h[-2:], h, h[:2]], np.ones(5), "same")[2:-2]
    icpt, slope = b[0] + (int(np.argmax(h)) + 0.5) * p0 / nb, p0
    for tol in (0.12, 0.08, 0.05, 0.04, 0.03):
        j = np.round((b - icpt) / slope)
        ok = np.abs(b - (icpt + slope * j)) < tol
        if ok.sum() < 12:
            return None
        slope, icpt = np.polyfit(j[ok], b[ok], 1)
    j = np.round((b - icpt) / slope)
    frac = float(np.mean(np.abs(b - (icpt + slope * j)) < 0.04))
    if frac < 0.5 or not (0.25 < slope < 1.5):
        return None
    return float(icpt), float(slope), frac


def _env_grave(y, sr, hop=256):
    from scipy.signal import butter as _bt, sosfilt as _sf
    yl = _sf(_bt(4, 150, "low", fs=sr, output="sos"), y)
    e1 = librosa.onset.onset_strength(y=yl, sr=sr, hop_length=hop)
    e2 = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    n = min(len(e1), len(e2))
    env = e1[:n] / (e1[:n].std() + 1e-9) + 0.5 * e2[:n] / (e2[:n].std() + 1e-9)
    env = np.maximum(env - np.median(env), 0.0)
    return env, np.arange(n) * hop / float(sr)


def _linea_de_audio(env, t, bpm0, rango=0.03, paso=0.0001):
    """Línea de pulso fija buscada directamente sobre los golpes del audio (peine de períodos)."""
    p0 = 60.0 / float(bpm0)
    mejor = (-1.0, None, None)
    scores = []
    for f in np.arange(1.0 - rango, 1.0 + rango + 1e-9, paso):
        p = p0 * f
        nb = max(16, int(round(p / 0.004)))
        bins = np.floor(np.mod(t, p) / p * nb).astype(int)
        h = np.bincount(bins, weights=env, minlength=nb)
        hs = np.convolve(np.r_[h[-2:], h, h[:2]], np.ones(3) / 3, "same")[2:-2]
        k = int(hs.argmax())
        sc = float(hs[k] / (len(env) / nb))
        scores.append(sc)
        if sc > mejor[0]:
            mejor = (sc, p, (k + 0.5) * p / nb)
    sc, p, ph = mejor
    med = float(np.median(scores)) if scores else 1.0
    return ph, p, sc / max(med, 1e-6)


def _grilla_final(res, linea):
    """Reemplaza beats/downbeats/bpm de `res` por la línea de pulso (icpt, período)."""
    icpt, slope = float(linea[0]), float(linea[1])
    dur = float(res["duration"])
    j0 = int(np.ceil((0.0 - icpt) / slope)); j1 = int(np.floor((dur - icpt) / slope))
    jj = np.arange(j0, j1 + 1)
    bt = icpt + slope * jj
    d_raw = np.asarray(res.get("downbeats_full") or [], dtype=np.float64)
    modo = 0
    if len(d_raw):
        jd = np.round((d_raw - icpt) / slope)
        sel = np.abs(d_raw - (icpt + slope * jd)) < 0.05
        pos = (jd[sel] if sel.sum() >= 4 else jd).astype(int) % 4
        modo = int(np.bincount(pos, minlength=4).argmax())
    db = bt[(jj % 4) == modo]
    def _ralo(v, tope):
        v = list(map(float, v))
        return v if len(v) <= tope else v[::len(v) // tope + 1]
    res["beats_full"] = list(map(float, bt)); res["beats"] = _ralo(bt, 400)
    res["downbeats_full"] = list(map(float, db)); res["downbeats"] = _ralo(db, 200)
    bpm_n = 60.0 / slope
    if abs(bpm_n - float(res["bpm"])) / float(res["bpm"]) < 0.03:
        res["bpm"] = float(bpm_n)
    res["grid"] = 1


def _limpiar_grilla_cache(res):
    """Versión barata (sin audio) para análisis ya guardados. Devuelve True si la grilla quedó regular."""
    if res.get("grid") == 1:
        return True
    try:
        ln = _linea_de_beats(res.get("beats_full") or [])
        if ln is None:
            return False
        _grilla_final(res, ln)
        return True
    except Exception:
        return False


def _analizar_archivo(path):
    y, sr = librosa.load(path, sr=22050, mono=True)

    rms_array = librosa.feature.rms(y=y, frame_length=2048, hop_length=1024)[0]
    rms_medio = float(np.mean(rms_array))
    if rms_medio > 1e-6:
        auto_gain = float(np.clip(TARGET_LUFS_RMS / rms_medio, 0.25, 4.0))
    else:
        auto_gain = 1.0

    tempo, beats = detect_beats(y, sr)
    tempo, beats = _plegar_tempo(tempo, beats, y, sr)
    # Si el nombre del archivo trae su BPM y el análisis no coincide (>6 %), se vuelve a seguir el pulso
    # usando ese BPM como guía (corrige errores de octava y de 3:2 que librosa comete).
    hint = _pista_bpm(path)
    if hint and abs(tempo - hint) / hint > 0.06:
        try:
            b2 = detect_beats_con_pista(y, sr, hint)
            g2 = _bpm_de_grilla(b2)
            if g2 and abs(g2 - hint) / hint < 0.06:
                beats, tempo = b2, g2
        except Exception:
            pass
    fino = _bpm_de_grilla(beats)                    # BPM preciso desde la grilla (si coincide con el estimado)
    if fino and abs(fino - tempo) / tempo < 0.04:
        tempo = fino
    duration = librosa.get_duration(y=y, sr=sr)
    kicks = detect_kicks(y, sr)
    downbeats = detect_downbeats(y, sr, beats)
    try:                                              # grilla regular: la mejor entre la de beats y la del audio
        env_g, t_g = _env_grave(y, sr)
        def _score(icpt, per):
            bt = icpt + per * np.arange(0, int(duration / per) + 1)
            bt = bt[(bt > 1.0) & (bt < duration - 1.0)]
            return float(np.mean(np.interp(bt, t_g, env_g))) if len(bt) else 0.0
        cands = []
        lb = _linea_de_beats(beats)
        if lb is not None:
            cands.append((_score(lb[0], lb[1]), (lb[0], lb[1])))
        ph, per, ratio = _linea_de_audio(env_g, t_g, tempo)
        brr = np.asarray(beats, dtype=np.float64)
        dentro = float(np.mean(np.abs(brr - (ph + per * np.round((brr - ph) / per))) < 0.06)) if len(brr) else 0.0
        if ratio >= 3.2 and dentro >= 0.4 and abs(60.0 / per - tempo) / tempo < 0.03:
            cands.append((_score(ph, per), (ph, per)))
        grilla = max(cands, key=lambda c: c[0])[1] if cands else None
    except Exception:
        import traceback; traceback.print_exc()
        grilla = None

    step = max(1, len(rms_array) // 2000)
    rms_small = rms_array[::step].tolist()

    if len(beats) > 400:
        skip = len(beats) // 400 + 1
        beats_draw = beats[::skip]
    else:
        beats_draw = beats
    if len(kicks) > 400:
        skip = len(kicks) // 400 + 1
        kicks_draw = kicks[::skip]
    else:
        kicks_draw = kicks
    if len(downbeats) > 200:
        skip = len(downbeats) // 200 + 1
        downbeats_draw = downbeats[::skip]
    else:
        downbeats_draw = downbeats

    res_out = {
        "bpm": float(tempo),
        "ver": 4,
        "duration": float(duration),
        "auto_gain": auto_gain,
        "beats": [float(b) for b in beats_draw],
        "kicks": [float(k) for k in kicks_draw],
        "downbeats": [float(d) for d in downbeats_draw],
        "beats_full": [float(b) for b in beats],
        "downbeats_full": [float(d) for d in downbeats],
        "kicks_full": [float(k) for k in kicks],
        "waveform": rms_small,
    }
    if grilla is not None:
        _grilla_final(res_out, grilla)
    else:
        res_out["grid"] = 0                             # no hay pulso fijo claro: se queda la grilla detectada
    return res_out


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
                self.done.emit(self.path, data)     # caché viejo sin auto_gain: lo calcula el deck del audio ya cargado
                return

            result = analizar_archivo(self.path)
            _guardar_cache(cache_key, result)
            self.done.emit(self.path, result)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.done.emit(self.path, {"error": str(e)})


def _guardar_cache(cache_key, result):
    tmp = Path(str(cache_key) + ".tmp")
    with open(tmp, "w") as f:
        json.dump(result, f)
    os.replace(tmp, cache_key)


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
                    print(f"Analizado: {os.path.basename(ruta)} -> {result['bpm']:.1f} BPM")
                    if time.monotonic() - t0 > 60.0:
                        print(f"[análisis] ese tema tardó {time.monotonic() - t0:.0f} s")
            except Exception:
                import traceback; traceback.print_exc()
            self.tema_listo.emit(ruta)
            self.progreso.emit(i, total)


def load_audio_stereo(path, sr=44100):
    y, _ = librosa.load(path, sr=sr, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    return y.T, sr


# =====================================================================
# 3) DECK
# =====================================================================
class EtiquetaElidida(QLabel):
    def __init__(self, texto=""):
        super().__init__()
        self._completo = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setText(texto)

    def setText(self, t):
        self._completo = t or ""
        self._recortar()

    def texto_completo(self):
        return self._completo

    def _recortar(self):
        w = self.width()
        if w <= 20:
            mostrar = self._completo
        else:
            mostrar = self.fontMetrics().elidedText(self._completo, Qt.TextElideMode.ElideRight, w - 6)
        if mostrar != super().text():
            super().setText(mostrar)
        self.setToolTip(self._completo if mostrar != self._completo else "")

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._recortar()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.FontChange:
            self._recortar()


class Deck(QFrame):
    def __init__(self, name, color, on_analysis_cb):
        super().__init__()
        self.name = name
        self.on_analysis_cb = on_analysis_cb
        self.path = None
        self.analysis = None
        self.audio = None
        self.sr = 44100
        self.cursor = 0
        self._cursor_frac = 0.0
        self.playing = False
        self.volume = 0.8
        self.auto_gain = 1.0
        self.tempo_rate = 1.0
        self.trim = 1.0
        self.on_play_cb = None
        self.on_reset_cb = None
        self.lock = threading.Lock()
        self.original_bpm = None

        self.setAcceptDrops(True)
        self.setStyleSheet(
            f"Deck {{ background-color: {color}; border: 2px dashed #888; border-radius: 8px; }}"
        )
        self.setFixedHeight(150)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(3)

        r1 = QHBoxLayout()
        self.lbl_title = QLabel(f"DECK {name}")
        self.lbl_title.setStyleSheet("color:white; font-size:15px; font-weight:bold;")
        self.lbl_title.setFixedWidth(70)
        r1.addWidget(self.lbl_title)
        self.lbl_track = EtiquetaElidida("Arrastrá una canción aquí")
        self.lbl_track.setStyleSheet("color:#ddd; font-size:11px;")
        r1.addWidget(self.lbl_track, stretch=1)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        self.lbl_bpm = QLabel("BPM: --")
        self.lbl_bpm.setStyleSheet("color:#ffd; font-size:11px;")
        self.lbl_bpm.setFixedWidth(220)
        r2.addWidget(self.lbl_bpm)
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("color:white; font-size:11px;")
        r2.addWidget(self.lbl_time, stretch=1)
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(4)
        self.btn_load = QPushButton("📂")
        self.btn_play = QPushButton("▶")
        self.btn_pause = QPushButton("⏸")
        self.btn_stop = QPushButton("⏹")
        self.btn_cue = QPushButton("CUE")
        self.btn_reset = QPushButton("⟲")
        for b in (self.btn_load, self.btn_play, self.btn_pause,
                  self.btn_stop, self.btn_cue, self.btn_reset):
            b.setFixedHeight(38); b.setFixedWidth(58); r3.addWidget(b)
            fb = b.font(); fb.setPointSizeF(17.0 if b is not self.btn_cue else 12.0); fb.setBold(True); b.setFont(fb)
        self.btn_load.clicked.connect(self.load_dialog)
        self.btn_play.clicked.connect(self.play)
        self.btn_pause.clicked.connect(self.pause)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_cue.clicked.connect(self.cue)
        self.btn_reset.clicked.connect(lambda *_: self.reset_tempo())
        self.btn_reset.setToolTip("Resetear el tempo al 100 % (el tema sigue donde está)")
        r3.addStretch()
        lay.addLayout(r3)

        r4 = QHBoxLayout()
        r4.addWidget(QLabel("Vol"))
        self.sld_vol = QSlider(Qt.Orientation.Horizontal)
        self.sld_vol.setRange(0, 100); self.sld_vol.setValue(80)
        r4.addWidget(self.sld_vol, stretch=1)
        r4.addWidget(QLabel("Tempo"))
        self.sld_tempo = QSlider(Qt.Orientation.Horizontal)
        self.sld_tempo.setRange(50, 200); self.sld_tempo.setValue(100)
        r4.addWidget(self.sld_tempo, stretch=1)
        lay.addLayout(r4)

        self.sld_vol.valueChanged.connect(self._update_vol)
        self.sld_tempo.valueChanged.connect(self._update_tempo)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isfile(p) and p.lower().endswith(SUPPORTED):
                self.load_track(p)
                break

    def load_dialog(self):
        f, _ = QFileDialog.getOpenFileName(
            self, f"Cargar en Deck {self.name}", "", "Audio (*.mp3 *.wav *.flac *.ogg *.m4a)"
        )
        if f:
            self.load_track(f)

    def load_track(self, path):
        self.stop()
        with self.lock:
            self.audio = None
            self.cursor = 0
            self._cursor_frac = 0.0
        self.analysis = None
        self.original_bpm = None
        self.auto_gain = 1.0
        self._ag_listo = False
        self.path = path
        self.lbl_track.setText(os.path.basename(path))
        self.lbl_bpm.setText("⏳ Analizando…")
        self.analyzer = Analyzer(path)
        _mantener_vivo(self.analyzer)
        self.analyzer.done.connect(self._on_analysis)
        self.analyzer.start()
        threading.Thread(target=self._load_audio, args=(path,), daemon=True).start()

    def _load_audio(self, path):
        try:
            y, sr = load_audio_stereo(path, sr=44100)
            # TODO lo pesado (copia contigua, Auto-Gain) FUERA del lock: el lock del deck lo toma
            # también el callback de audio, y si se queda esperando se oye un corte en lo que suena.
            y32 = np.ascontiguousarray(y, dtype=np.float32)
            ag = self._calc_auto_gain(y32)
            with self.lock:
                if path != self.path:
                    return
                self.auto_gain = ag
                self._ag_listo = True
                self.audio = y32
                self.sr = sr
                self.cursor = 0
                self._cursor_frac = 0.0
        except Exception as e:
            print("Error cargando audio:", e)

    @staticmethod
    def _calc_auto_gain(audio):
        """Auto-Gain a partir del audio ya cargado (sin librosa ni re-análisis)."""
        try:
            n = (len(audio) // 1024) * 1024
            if n < 2048:
                return 1.0
            # media L/R por bloques de 1024, sin copias gigantes de float64
            bloques = audio[:n].reshape(-1, 1024, 2)
            e = np.einsum("bij,bij->b", bloques, bloques, dtype=np.float64) / (1024 * 2)
            rms_medio = float(np.mean(np.sqrt(e)))
            return float(np.clip(TARGET_LUFS_RMS / rms_medio, 0.25, 4.0)) if rms_medio > 1e-6 else 1.0
        except Exception:
            return 1.0

    @staticmethod
    def _afinar_bpm(res):
        """El BPM global de librosa suele errar 1-2 %. Con la grilla de beats detectada se calcula uno
        mucho más preciso (media de los intervalos sin los atípicos). Un error de 1 % en el BPM
        hace que, en una mezcla de 10 s, los golpes se corran ~100 ms y se oiga doble (flam)."""
        try:
            b = np.asarray(res.get("beats_full") or [], dtype=np.float64)
            if len(b) < 16:
                return
            iv = np.diff(b)
            m = float(np.median(iv))
            k = iv[np.abs(iv - m) < 0.08 * m]
            if len(k) < 12 or m <= 0:
                return
            fino = 60.0 / float(np.mean(k))
            if abs(fino - res["bpm"]) / res["bpm"] < 0.03:      # solo afina; no cambia de "mitad/doble"
                res["bpm_librosa"] = res["bpm"]
                res["bpm"] = float(fino)
        except Exception:
            pass

    def _on_analysis(self, path, res):
        if path != self.path:
            return
        if "error" in res:
            self.lbl_bpm.setText("Error")
            return
        _limpiar_grilla_cache(res)
        self._afinar_bpm(res)
        self.analysis = res
        self.original_bpm = res["bpm"]
        if not getattr(self, "_ag_listo", False):
            self.auto_gain = res.get("auto_gain", 1.0)
        self._update_bpm_label()
        self.lbl_time.setText(f"00:00 / {fmt_time(res['duration'])}")
        if self.on_analysis_cb:
            self.on_analysis_cb(self.name, res)

    def _update_bpm_label(self):
        if self.original_bpm is None:
            return
        eff = self.original_bpm * self.tempo_rate
        self.lbl_bpm.setText(f"BPM: {eff:6.2f} (AutoGain: {self.auto_gain:.2f}x)")

    @property
    def rate_eff(self):
        return self.tempo_rate * self.trim

    def play(self):
        if self.audio is None:
            return
        if self.on_play_cb is not None and not self.playing:
            try:
                self.on_play_cb(self)
            except Exception:
                import traceback; traceback.print_exc()
        self.playing = True

    def pause(self):
        self.playing = False

    def stop(self):
        self.playing = False
        self.trim = 1.0
        with self.lock:
            self.cursor = 0
            self._cursor_frac = 0.0

    def reset_tempo(self):
        """Solo vuelve el tempo al 100 % (y el microajuste a 1.0). NO toca la posición del tema."""
        self.trim = 1.0
        # Resetea el tempo_rate al 100% (slider incluido, sin disparar señales)
        if abs(self.tempo_rate - 1.0) > 1e-6:
            self.tempo_rate = 1.0
            pct = 100
            if self.sld_tempo.value() != pct:
                self.sld_tempo.blockSignals(True)
                self.sld_tempo.setValue(pct)
                self.sld_tempo.blockSignals(False)
        self._update_bpm_label()
        # Avisar a la ventana (redibuja timeline, status, etc.)
        if self.on_reset_cb is not None:
            try:
                self.on_reset_cb(self)
            except Exception:
                import traceback; traceback.print_exc()

    reset_time = reset_tempo      # nombre anterior, por compatibilidad

    def cue(self):
        if not self.analysis:
            return
        kicks = self.analysis.get("kicks_full") or self.analysis.get("kicks", [])
        fb = kicks[0] if kicks else (
            self.analysis["beats_full"][0] if self.analysis.get("beats_full")
            else (self.analysis["beats"][0] if self.analysis.get("beats") else 0)
        )
        with self.lock:
            self.cursor = int(fb * self.sr)
            self._cursor_frac = 0.0

    def _update_vol(self):
        self.volume = self.sld_vol.value() / 100.0

    def _update_tempo(self):
        self.tempo_rate = self.sld_tempo.value() / 100.0
        self._update_bpm_label()

    def set_tempo_from_fader(self, rate):
        rate = float(np.clip(rate, 0.5, 2.0))
        self.tempo_rate = rate
        pct = int(round(rate * 100))
        if self.sld_tempo.value() != pct:
            self.sld_tempo.blockSignals(True)
            self.sld_tempo.setValue(pct)
            self.sld_tempo.blockSignals(False)
        self._update_bpm_label()

    def position_seconds(self):
        with self.lock:
            return self.cursor / self.sr if self.audio is not None else 0.0

    def set_position_seconds(self, t):
        if self.audio is None:
            return
        t = float(np.clip(t, 0.0, len(self.audio) / self.sr - 0.001))
        with self.lock:
            self.cursor = int(t * self.sr)
            self._cursor_frac = 0.0

    def tick(self):
        if self.analysis and self.audio is not None:
            pos = self.position_seconds()
            self.lbl_time.setText(f"{fmt_time(pos)} / {fmt_time(self.analysis['duration'])}")

    def render(self, frames):
        out = np.zeros((frames, 2), dtype=np.float32)
        with self.lock:
            if not self.playing or self.audio is None:
                return out
            rate = self.rate_eff
            n_audio = len(self.audio)

            ganancia_total = self.volume * self.auto_gain

            if abs(rate - 1.0) < 1e-9 and self._cursor_frac == 0.0:
                end = self.cursor + frames
                chunk = self.audio[self.cursor:end]
                if len(chunk) < frames:
                    pad = np.zeros((frames - len(chunk), 2), dtype=np.float32)
                    chunk = np.vstack([chunk, pad])
                    self.playing = False
                out[:] = chunk * ganancia_total
                self.cursor += frames
            else:
                pos = self.cursor + self._cursor_frac + np.arange(frames, dtype=np.float64) * rate
                i1 = np.floor(pos).astype(np.int64)
                t = (pos - i1).astype(np.float32)[:, None]
                if i1[-1] + 2 >= n_audio:
                    self.playing = (i1[0] + 2 < n_audio)
                idx = np.clip(np.stack([i1 - 1, i1, i1 + 1, i1 + 2]), 0, n_audio - 1)
                p0, p1, p2, p3 = (self.audio[idx[k]] for k in range(4))
                t2 = t * t; t3 = t2 * t
                y = 0.5 * ((2 * p1) + (-p0 + p2) * t
                           + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                           + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
                valid = (pos < n_audio - 1)[:, None]
                out[:] = (y * valid).astype(np.float32) * ganancia_total
                total = self._cursor_frac + frames * rate
                int_adv = int(total)
                self._cursor_frac = total - int_adv
                self.cursor += int_adv
        return out


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
                    objetivo = -sobre * (1.0 - 1.0 / ratio) + self._mk[i]
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
        if self.mb.manual:           # modo manual: sin EQ inteligente, solo la multibanda con tus valores
            self.mb.exceso = None
            return self.mb.procesar(x)
        y = self.eq.procesar(x)
        self.mb.exceso = self.eq.exceso_grupos()
        return self.mb.procesar(y)


# =====================================================================
# 3.5) MIXER GLOBAL
# =====================================================================
class GlobalMixer:
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

    def start(self):
        if self.stream is not None:
            return
        self.stream = sd.OutputStream(
            samplerate=self.sr, channels=2, dtype="float32",
            callback=self._cb, blocksize=self.blocksize, latency=0.12
        )
        self.stream.start()

    def set_volumen(self, v01):
        self.gain_obj = float(max(0.0, min(1.0, v01))) ** 2

    def stop(self):
        if self.stream:
            self.stream.stop(); self.stream.close(); self.stream = None

    def _cb(self, outdata, frames, time_info, status):
        a = self.deck_a.render(frames)
        b = self.deck_b.render(frames)
        self.snap_pos = (self.deck_a.cursor + self.deck_a._cursor_frac, self.deck_b.cursor + self.deck_b._cursor_frac)
        mix = a + b
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
        pico = np.abs(mix)
        if pico.size and float(pico.max()) > 0.9:
            exceso = np.maximum(pico - 0.9, 0.0)
            mix = np.where(pico > 0.9,
                           np.sign(mix) * (0.9 + 0.1 * np.tanh(exceso / 0.1)),
                           mix)
        g0, g1 = self._gain_act, self.gain_obj
        if g0 != g1:
            mix = mix * np.linspace(g0, g1, frames, dtype=np.float32)[:, None]
            self._gain_act = g1
        elif g1 != 1.0:
            mix = mix * g1
        outdata[:] = mix.astype(np.float32)


# =====================================================================
# 3.7) FORMA DEL CRUCE
# =====================================================================
CONFIG_JSON = Path(__file__).parent / "cache" / "config.json"
DEF_PUNTO_A = 0.50
DEF_PUNTO_B = 0.0


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


class GraficoCruce(QWidget):
    def __init__(self):
        super().__init__()
        self.punto_a = DEF_PUNTO_A; self.punto_b = DEF_PUNTO_B; self.avance = None
        self.setMinimumHeight(75)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def actualizar(self, pa, pb, avance=None):
        self.punto_a, self.punto_b, self.avance = pa, pb, avance
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, m = self.width(), self.height(), 6
        p.fillRect(self.rect(), QColor("#141414"))
        p.setPen(QPen(QColor("#ffffff"), 2)); p.drawRect(m, m, w - 2 * m - 1, h - 2 * m - 1)
        x0, x1, yt, yb = m + 2.0, w - m - 2.0, m + 2.0, h - m - 2.0
        pa, pb = [], []
        for i in range(61):
            t = i / 60
            vs, ve = perfil_cruce_ab(t, self.punto_a, self.punto_b)
            x = x0 + (x1 - x0) * t
            pa.append(QPointF(x, yb - vs * (yb - yt))); pb.append(QPointF(x, yb - ve * (yb - yt)))
        p.setPen(QPen(QColor("#e74c3c"), 3)); p.drawPolyline(QPolygonF(pa))
        p.setPen(QPen(QColor("#3498db"), 3)); p.drawPolyline(QPolygonF(pb))
        if self.avance is not None:
            xa = x0 + (x1 - x0) * max(0.0, min(1.0, self.avance))
            p.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine)); p.drawLine(QPointF(xa, yt), QPointF(xa, yb))
        p.end()


class PanelCruce(QFrame):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(230); self.setMaximumWidth(300)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(3)
        self.chk = QCheckBox("🎚 Forma de cruce A/B (sin tilde: clásico)")
        self.chk.setChecked(ventana.cruce_ab)
        lay.addWidget(self.chk)
        self.graf = GraficoCruce(); lay.addWidget(self.graf)

        def fila(texto, color, valor, tip):
            r = QHBoxLayout()
            l = QLabel(texto); l.setStyleSheet(f"color:{color}; font-weight:bold;"); l.setToolTip(tip)
            sl = QSlider(Qt.Orientation.Horizontal); sl.setRange(0, 95); sl.setValue(int(round(valor * 100))); sl.setToolTip(tip)
            lv = QLabel(f"{sl.value()}%"); lv.setMinimumWidth(40); lv.setAlignment(Qt.AlignmentFlag.AlignRight)
            r.addWidget(l); r.addWidget(sl, 1); r.addWidget(lv); lay.addLayout(r)
            return sl, lv
        self.sl_a, self.lv_a = fila("A (sale):", "#e74c3c", ventana.punto_a, "Momento en que el tema que sale comienza a bajar.")
        self.sl_b, self.lv_b = fila("B (entra):", "#3498db", ventana.punto_b, "Momento en que el tema que entra comienza a subir.")
        self.lbl_dur = QLabel(); self.lbl_dur.hide()
        b_def = QPushButton("Valores por defecto"); b_def.clicked.connect(self._defecto)
        lay.addWidget(b_def)
        lay.addStretch()

        self.sl_a.valueChanged.connect(self._cambio); self.sl_b.valueChanged.connect(self._cambio)
        self.chk.toggled.connect(self._cambio)
        self._timer = QTimer(self); self._timer.timeout.connect(self._refrescar); self._timer.start(50)
        self.lv_a.setText(f"{self.sl_a.value()}%"); self.lv_b.setText(f"{self.sl_b.value()}%")

    def _defecto(self):
        self.sl_a.setValue(int(DEF_PUNTO_A * 100)); self.sl_b.setValue(int(DEF_PUNTO_B * 100))

    def _cambio(self, *_):
        self.lv_a.setText(f"{self.sl_a.value()}%"); self.lv_b.setText(f"{self.sl_b.value()}%")
        self.v.set_forma_cruce(self.sl_a.value() / 100.0, self.sl_b.value() / 100.0, self.chk.isChecked())
        self._refrescar()

    def _refrescar(self):
        if not hasattr(self.v, "spin_mix"):
            return
        x = self.v.crossfader.value() / 100.0
        t = x if self.v._cf_dir == "AB" else 1.0 - x
        self.graf.actualizar(self.sl_a.value() / 100.0, self.sl_b.value() / 100.0, t)
        self.lbl_dur.setText(f"⏱ Mezcla: {self.v.spin_mix.value()} s")


# =====================================================================
# 3.6) BARRA DE PROGRESO CON MARCA (AUTO-ENGANCHE)
# =====================================================================
class BarraProgresoConMarca(QWidget):
    marca_cambiada = Signal(float)
    marca_cruzada = Signal(float)

    MARGEN = 10

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(50)
        self.setMaximumHeight(50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progreso = 0.0
        self.prog_seg = 0.0
        self.dur = 0.0
        self.marca = -1.0
        self._arrastrando = False
        self._arrastrando_marca = False
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_progreso(self, p, seg=0.0, dur=0.0):
        p = max(0.0, min(1.0, float(p)))
        cambio = (abs(p - self.progreso) > 1e-4
                  or abs(seg - self.prog_seg) > 0.05
                  or abs(dur - self.dur) > 0.05)
        self.progreso = p
        self.prog_seg = seg
        self.dur = dur
        if cambio:
            self.update()

    def set_marca(self, m):
        self.marca = float(m)
        self.update()

    def _x_de_frac(self, f):
        w = self.width()
        m = self.MARGEN
        return m + f * max(1, (w - 2 * m))

    def _frac_de_x(self, x):
        w = self.width()
        m = self.MARGEN
        return max(0.0, min(1.0, (x - m) / max(1, (w - 2 * m))))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        m = self.MARGEN

        p.fillRect(self.rect(), QColor("#0d0d0d"))

        y_top = 3
        y_sep = 8
        p.setPen(QPen(QColor("#3a3a3a"), 1))
        for f in (0.25, 0.5, 0.75):
            x = self._x_de_frac(f)
            p.drawLine(int(x), y_top, int(x), y_sep)

        y_prog_t = 10                 # la barra de progreso ocupa casi todo el fondo negro
        y_prog_b = h - 4
        hh = y_prog_b - y_prog_t

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#1e1e1e")))
        p.drawRoundedRect(m, y_prog_t, w - 2 * m, hh, 3, 3)

        if self.progreso > 0.0:
            pw = int(self.progreso * (w - 2 * m))
            if pw > 0:
                p.setBrush(QBrush(QColor("#2f9fd0")))
                p.drawRoundedRect(m, y_prog_t, pw, hh, 3, 3)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#444"), 1))
        p.drawRoundedRect(m, y_prog_t, w - 2 * m, hh, 3, 3)

        if self.dur > 0:
            txt = f"{fmt_time(self.prog_seg)}  /  {fmt_time(self.dur)}"
        else:
            txt = "--:--  /  --:--"
        f = self.font(); f.setPointSizeF(10.5); f.setBold(True); p.setFont(f)
        p.setPen(QPen(QColor("#fff"), 1))
        p.drawText(m + 6, y_prog_t, w - 2 * m - 12, hh,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)

        if self.marca >= 0:
            txt_m = f"⚓ {self.marca * 100:.1f}%"
            p.setPen(QPen(QColor("#ff6b6b"), 1))
            p.drawText(m + 6, y_prog_t, w - 2 * m - 12, hh,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, txt_m)

        if self.marca >= 0:                      # la marca va AL FRENTE: se dibuja al final, encima de la barra
            xm = self._x_de_frac(self.marca)
            p.setPen(QPen(QColor("#000000"), 4))                 # borde oscuro para que se vea sobre lo celeste
            p.drawLine(int(xm), y_top, int(xm), h - 2)
            p.setPen(QPen(QColor("#ff3b3b"), 2))
            p.drawLine(int(xm), y_top, int(xm), h - 2)
            p.setBrush(QBrush(QColor("#ff3b3b")))
            p.setPen(QPen(QColor("#000000"), 1))
            p.drawPolygon(QPolygonF([QPointF(xm - 7, y_top - 1), QPointF(xm + 7, y_top - 1), QPointF(xm, y_top + 8)]))
            p.drawPolygon(QPolygonF([QPointF(xm - 7, h - 1), QPointF(xm + 7, h - 1), QPointF(xm, h - 9)]))

        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._arrastrando = True
            self._set_marca_desde_x(ev.position().x())

    def mouseMoveEvent(self, ev):
        if self._arrastrando:
            self._set_marca_desde_x(ev.position().x())

    def mouseReleaseEvent(self, ev):
        self._arrastrando = False

    def mouseDoubleClickEvent(self, ev):
        self.marca = -1.0
        self.marca_cambiada.emit(-1.0)
        self.update()

    def _set_marca_desde_x(self, x):
        f = self._frac_de_x(x)
        self.marca = f
        self.marca_cambiada.emit(f)
        self.update()

    def sizeHint(self):
        return QSize(500, 50)


# =====================================================================
# 3.7) BIBLIOTECA
# =====================================================================
BIBLIOTECA_JSON = Path(__file__).parent / "cache" / "biblioteca.json"


def _escanear(rutas):
    out = []
    for p in rutas:
        if os.path.isdir(p):
            for raiz, dirs, archivos in os.walk(p):
                dirs.sort(key=str.lower)
                for f in sorted(archivos, key=str.lower):
                    if f.lower().endswith(SUPPORTED):
                        out.append(os.path.join(raiz, f))
        elif os.path.isfile(p) and p.lower().endswith(SUPPORTED):
            out.append(p)
    return out


class Biblioteca(QListWidget):
    cambio = Signal()
    nuevos = Signal()          # se agregaron temas: hay que analizarlos
    ROL_NOMBRE = Qt.ItemDataRole.UserRole + 1

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setUniformItemSizes(True)
        self.setAlternatingRowColors(True)
        f = self.font(); f.setPointSize(9); self.setFont(f)
        self._rutas = set()
        self._cola = set()         # temas esperando su análisis (se muestran con ⏳)

    @staticmethod
    def _clave(p):
        return os.path.normcase(os.path.abspath(p))

    def _nombre(self, it):
        n = it.data(self.ROL_NOMBRE)
        return n if n is not None else it.text()

    def _refrescar_textos(self):
        for i in range(self.count()):
            it = self.item(i)
            esperando = self._clave(it.data(Qt.ItemDataRole.UserRole)) in self._cola
            nuevo = ("⏳ " if esperando else "") + self._nombre(it)
            if it.text() != nuevo:
                it.setText(nuevo)

    def marcar(self, rutas):
        """Los temas de esta lista aparecen con el reloj de arena hasta que se los analiza."""
        self._cola = {self._clave(r) for r in rutas}
        self._refrescar_textos()

    def quitar_de_cola(self, ruta):
        k = self._clave(ruta)
        if k in self._cola:
            self._cola.discard(k)
            self._refrescar_textos()

    def agregar(self, rutas):
        n = 0
        self.setUpdatesEnabled(False)
        try:
            for p in _escanear(rutas):
                clave = os.path.normcase(os.path.abspath(p))
                if clave in self._rutas:
                    continue
                self._rutas.add(clave)
                nombre = os.path.splitext(os.path.basename(p))[0]
                it = QListWidgetItem(nombre)
                it.setData(self.ROL_NOMBRE, nombre)
                it.setData(Qt.ItemDataRole.UserRole, p)
                it.setToolTip(p)
                self.addItem(it)
                n += 1
        finally:
            self.setUpdatesEnabled(True)
        if n:
            self.cambio.emit()
            self.nuevos.emit()
        return n

    def quitar_seleccion(self):
        for it in self.selectedItems():
            p = it.data(Qt.ItemDataRole.UserRole)
            self._rutas.discard(os.path.normcase(os.path.abspath(p)))
            self.takeItem(self.row(it))
        self.cambio.emit()

    def limpiar(self):
        self.clear(); self._rutas.clear(); self._cola.clear(); self.cambio.emit()

    def pintar(self, ruta_a, ruta_b):
        ka = os.path.normcase(os.path.abspath(ruta_a)) if ruta_a else None
        kb = os.path.normcase(os.path.abspath(ruta_b)) if ruta_b else None
        for i in range(self.count()):
            it = self.item(i)
            k = os.path.normcase(os.path.abspath(it.data(Qt.ItemDataRole.UserRole)))
            if k == ka:
                it.setBackground(QBrush(QColor("#a8cdf2"))); it.setForeground(QBrush(QColor("#10253f")))
            elif k == kb:
                it.setBackground(QBrush(QColor("#f2adc4"))); it.setForeground(QBrush(QColor("#4a0f26")))
            else:
                it.setData(Qt.ItemDataRole.BackgroundRole, None)
                it.setData(Qt.ItemDataRole.ForegroundRole, None)

    def todas(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    @staticmethod
    def _bpm_de(ruta):
        try:
            cache = CACHE_DIR / (Path(ruta).stem + ".json")
            if cache.exists():
                with open(cache, encoding="utf-8") as f:
                    v = json.load(f).get("bpm")
                return float(v) if v is not None else None
        except Exception:
            pass
        return None

    def temas_sin_bpm(self):
        return [r for r in self.todas() if self._bpm_de(r) is None]

    def ordenar_por_bpm(self):
        self.setUpdatesEnabled(False)
        try:
            items = []
            while self.count() > 0:
                it = self.takeItem(0)
                ruta = it.data(Qt.ItemDataRole.UserRole)
                bpm = self._bpm_de(ruta)
                items.append((bpm, it))
            items.sort(key=lambda x: (x[0] is None,
                                      x[0] if x[0] is not None else 0.0,
                                      self._nombre(x[1]).lower()))
            for _, it in items:
                self.addItem(it)
        finally:
            self.setUpdatesEnabled(True)
        self.cambio.emit()

    def guardar(self):
        try:
            BIBLIOTECA_JSON.parent.mkdir(exist_ok=True)
            BIBLIOTECA_JSON.write_text(json.dumps(self.todas(), ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print("No se pudo guardar la biblioteca:", e)

    def cargar(self):
        try:
            rutas = json.loads(BIBLIOTECA_JSON.read_text(encoding="utf-8"))
            self.agregar([r for r in rutas if os.path.isfile(r)])
        except Exception:
            pass

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(i.data(Qt.ItemDataRole.UserRole)) for i in items])
        return md

    def supportedDropActions(self):
        return Qt.DropAction.CopyAction

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.source() is self or not e.mimeData().hasUrls():
            e.ignore(); return
        self.agregar([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Delete:
            self.quitar_seleccion()
        else:
            super().keyPressEvent(e)


# =====================================================================
# 4) TIMELINE
# =====================================================================
class UnifiedTimeline(QGraphicsView):
    def __init__(self, deck_a, deck_b, on_manito_cb=None):
        super().__init__()
        self.deck_a = deck_a
        self.deck_b = deck_b
        self.scene_ = QGraphicsScene()
        self.setScene(self.scene_)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setStyleSheet("background:#0a0a0a; border:1px solid #333;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(240)

        self.px_per_s = 40.0
        self._dragging = False
        self._last_x = 0.0
        self._dragging_deck = None

        self.manito_active = True
        self.on_manito_cb = on_manito_cb

        self.anchor_a = 0.0
        self.anchor_b = 0.0

    def t_to_x(self, t, W, anchor):
        center = W / 2.0
        return center + (t - anchor) * self.px_per_s

    def x_to_t(self, x, W, anchor):
        center = W / 2.0
        return anchor + (x - center) / self.px_per_s

    def set_zoom_px(self, px_per_s):
        self.px_per_s = float(np.clip(px_per_s, 3.0, 400.0))
        self.redraw()

    def _sync_anchors(self):
        if not (self.manito_active and self._dragging and self._dragging_deck == "A"):
            self.anchor_a = self.deck_a.position_seconds()
        if not (self.manito_active and self._dragging and self._dragging_deck == "B"):
            self.anchor_b = self.deck_b.position_seconds()

    def redraw(self):
        self.scene_.clear()

        W = max(100, self.viewport().width())      # tamaño REAL del visor: si se forzaba un mínimo mayor,
        H = max(60, self.viewport().height())      # la escena quedaba más grande que la vista y se cortaba
        self.scene_.setSceneRect(0, 0, W, H)

        mid = H / 2

        self._sync_anchors()
        anchor_a = self.anchor_a
        anchor_b = self.anchor_b

        if self.px_per_s > 150:   step_s = 0.5
        elif self.px_per_s > 60:  step_s = 1.0
        elif self.px_per_s > 20:  step_s = 5.0
        elif self.px_per_s > 8:   step_s = 10.0
        else:                     step_s = 30.0

        t_left = anchor_a - (W / 2) / self.px_per_s
        t_right = anchor_a + (W / 2) / self.px_per_s

        t = np.ceil(t_left / step_s) * step_s
        while t <= t_right:
            if t < 0:
                t += step_s
                continue
            x = self.t_to_x(t, W, anchor_a)
            ln = QGraphicsLineItem(x, 0, x, H)
            ln.setPen(QPen(QColor(45, 45, 45), 1))
            self.scene_.addItem(ln)
            txt = QGraphicsSimpleTextItem(fmt_time(t))
            txt.setBrush(QBrush(QColor(90, 90, 90)))
            f = QFont(); f.setPointSizeF(max(4.0, 7 * UI_ESCALA)); txt.setFont(f)
            txt.setPos(x + 2, 2)
            self.scene_.addItem(txt)
            t += step_s

        cl = QGraphicsLineItem(0, mid, W, mid)
        cl.setPen(QPen(QColor(60, 60, 60), 1))
        self.scene_.addItem(cl)

        if self.deck_a.analysis:
            self._draw_deck(self.deck_a.analysis, W, 0, mid - 1, anchor_a,
                            fill=QColor(0, 120, 200, 200),
                            beat_c=QColor(0, 220, 255, 120),
                            kick_c=QColor(255, 255, 255, 230),
                            downbeat_c=QColor(0, 255, 120, 220))

        if self.deck_b.analysis:
            self._draw_deck(self.deck_b.analysis, W, mid + 1, H, anchor_b,
                            fill=QColor(200, 60, 140, 200),
                            beat_c=QColor(255, 120, 200, 120),
                            kick_c=QColor(255, 255, 255, 230),
                            downbeat_c=QColor(255, 200, 0, 220))

        center_x = W / 2.0
        ph = QGraphicsLineItem(center_x, 0, center_x, H)
        ph.setPen(QPen(QColor(255, 255, 0), 2))
        self.scene_.addItem(ph)

        if self.manito_active:
            self.viewport().setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            self.viewport().setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def _draw_deck(self, analysis, W, top, bottom, anchor,
                   fill, beat_c, kick_c, downbeat_c):
        wf = analysis["waveform"]
        if not wf:
            return
        maxv = max(wf) or 1.0
        n = len(wf)
        dur = analysis["duration"]
        if dur <= 0:
            return
        block_h = bottom - top
        center_y = top + block_h / 2
        amp = block_h / 2 - 4

        poly = QPolygonF()
        for i, v in enumerate(wf):
            t = (i / n) * dur
            x = self.t_to_x(t, W, anchor)
            if x < -5 or x > W + 5:
                continue
            vn = (v / maxv) * amp
            poly.append(QPointF(x, center_y - vn))
        if poly.count() >= 2:
            for i in range(n - 1, -1, -1):
                v = wf[i]
                t = (i / n) * dur
                x = self.t_to_x(t, W, anchor)
                if x < -5 or x > W + 5:
                    continue
                vn = (v / maxv) * amp
                poly.append(QPointF(x, center_y + vn))
            item = QGraphicsPolygonItem(poly)
            item.setBrush(QBrush(fill))
            item.setPen(QPen(fill.darker(150), 0.5))
            self.scene_.addItem(item)

        for b in analysis.get("beats", []):
            x = self.t_to_x(b, W, anchor)
            if x < -2 or x > W + 2: continue
            ln = QGraphicsLineItem(x, top, x, bottom)
            ln.setPen(QPen(beat_c, 1))
            self.scene_.addItem(ln)

        for d in analysis.get("downbeats", []):
            x = self.t_to_x(d, W, anchor)
            if x < -2 or x > W + 2: continue
            ln = QGraphicsLineItem(x, top, x, bottom)
            ln.setPen(QPen(downbeat_c, 3))
            self.scene_.addItem(ln)

        for k in analysis.get("kicks", []):
            x = self.t_to_x(k, W, anchor)
            if x < -2 or x > W + 2: continue
            ln = QGraphicsLineItem(x, top, x, bottom)
            ln.setPen(QPen(kick_c, 2))
            self.scene_.addItem(ln)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            H = self.scene_.sceneRect().height()
            mid = H / 2
            y = event.position().y()
            self._dragging = True
            self._last_x = event.position().x()

            if self.manito_active:
                self._dragging_deck = "A" if y < mid else "B"
                self.viewport().setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            else:
                self._dragging_deck = None
                self._do_scrub(event.position().x(), y)

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        W = self.scene_.sceneRect().width()
        x = event.position().x()
        y = event.position().y()

        if self.manito_active and self._dragging_deck:
            dx = x - self._last_x
            dt = dx / self.px_per_s

            if self._dragging_deck == "A":
                new_anchor = self.anchor_a - dt
                dur = self.deck_a.analysis["duration"] if self.deck_a.analysis else 0
                self.anchor_a = float(np.clip(new_anchor, 0.0, max(0.0, dur)))
            else:
                new_anchor = self.anchor_b - dt
                dur = self.deck_b.analysis["duration"] if self.deck_b.analysis else 0
                self.anchor_b = float(np.clip(new_anchor, 0.0, max(0.0, dur)))

            self._last_x = x
            self.redraw()
        else:
            self._do_scrub(x, y)

    def mouseReleaseEvent(self, event):
        if self.manito_active and self._dragging_deck:
            if self._dragging_deck == "A":
                self.deck_a.set_position_seconds(self.anchor_a)
            else:
                self.deck_b.set_position_seconds(self.anchor_b)
            self.viewport().setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            if self.on_manito_cb:
                self.on_manito_cb(self._dragging_deck)
        self._dragging = False
        self._dragging_deck = None

    def _do_scrub(self, x, y):
        W = self.scene_.sceneRect().width()
        H = self.scene_.sceneRect().height()
        mid = H / 2

        if y < mid and self.deck_a.audio is not None:
            anchor_a = self.deck_a.position_seconds()
            t_new = self.x_to_t(x, W, anchor_a)
            self.deck_a.set_position_seconds(t_new)
        elif y >= mid and self.deck_b.audio is not None:
            anchor_b = self.deck_b.position_seconds()
            t_new = self.x_to_t(x, W, anchor_b)
            self.deck_b.set_position_seconds(t_new)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 0.87
        self.px_per_s = float(np.clip(self.px_per_s * factor, 3.0, 400.0))
        self.redraw()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.redraw()


# =====================================================================
# 5) SMART SYNC
# =====================================================================
class SmartSync:
    @staticmethod
    def _next_event_after(events, t_now, bpm):
        if not events:
            return t_now
        events = np.asarray(events)
        idx = np.searchsorted(events, t_now - 0.005)
        if idx < len(events):
            return float(events[idx])
        beat_dt = 60.0 / max(1e-6, bpm)
        last = events[-1]
        n = int(np.ceil((t_now - last) / beat_dt))
        return float(last + n * beat_dt)

    @staticmethod
    def compute_phase_error(master: Deck, slave: Deck, promedio=False, n_prom=6):
        if not (master.analysis and slave.analysis):
            return None

        rate_m = max(1e-6, master.rate_eff)
        rate_s = max(1e-6, slave.rate_eff)

        db_m = master.analysis.get("downbeats_full") or master.analysis.get("downbeats") or []
        db_s = slave.analysis.get("downbeats_full") or slave.analysis.get("downbeats") or []
        if not db_m or not db_s:
            return None

        t_m = master.position_seconds()
        t_s = slave.position_seconds()

        next_m = SmartSync._next_event_after(db_m, t_m, master.analysis["bpm"])
        next_s = SmartSync._next_event_after(db_s, t_s, slave.analysis["bpm"])

        falta_m = (next_m - t_m) / rate_m
        falta_s = (next_s - t_s) / rate_s
        err = falta_s - falta_m

        if promedio:
            arr_m = np.asarray(db_m, dtype=float)
            arr_s = np.asarray(db_s, dtype=float)
            i_m = int(np.searchsorted(arr_m, next_m - 1e-6))
            i_s = int(np.searchsorted(arr_s, next_s - 1e-6))
            n = int(min(n_prom, len(arr_m) - i_m, len(arr_s) - i_s))
            if n >= 2:
                f_m = (arr_m[i_m:i_m + n] - t_m) / rate_m
                f_s = (arr_s[i_s:i_s + n] - t_s) / rate_s
                err = float(np.mean(f_s - f_m))

        if len(db_s) >= 2:
            periodo = float(np.median(np.diff(np.asarray(db_s)))) / rate_s
        else:
            periodo = 4.0 * 60.0 / max(1e-6, slave.analysis["bpm"] * rate_s)
        if periodo > 0:
            err = ((err + periodo / 2.0) % periodo) - periodo / 2.0
        return err

    @staticmethod
    def _falta_suave(deck: Deck, n=12, pos=None):
        """Segundos REALES hasta el próximo downbeat y período real del compás, usando una grilla
        regular ajustada (regresión lineal ROBUSTA) sobre n downbeats vecinos: los downbeats mal
        detectados (compases de 2,26 s o 2,84 s en un tema de 2,62 s) se descartan en vez de arrastrar
        al entrante hacia adelante y hacia atrás."""
        if not deck.analysis:
            return None
        db = deck.analysis.get("downbeats_full") or deck.analysis.get("downbeats") or []
        arr = np.asarray(db, dtype=np.float64)
        if len(arr) < 3:
            return None
        t = (pos / deck.sr) if pos is not None else deck.position_seconds()
        rate = max(1e-6, deck.rate_eff)
        i = int(np.searchsorted(arr, t))
        lo = max(0, min(i - n // 2, len(arr) - n))
        seg = arr[lo:lo + n]
        if len(seg) < 3:
            return None
        k = np.arange(lo, lo + len(seg), dtype=np.float64)
        b, a = np.polyfit(k, seg, 1)             # t_k = a + b·k
        for tol in (0.08, 0.03):                 # 2 pasadas: se descartan los que se alejan de la recta
            ok = np.abs(seg - (a + b * k)) < tol
            if ok.sum() < max(4, len(seg) // 2):
                break
            b, a = np.polyfit(k[ok], seg[ok], 1)
        if not (b > 0.2):
            return None
        kn = np.ceil((t - a) / b - 1e-9)
        return float((a + b * kn - t) / rate), float(b / rate)

    @staticmethod
    def error_fase_suave(master: Deck, slave: Deck, pos_m=None, pos_s=None):
        """Cuánto va ATRASADO el entrante respecto de la grilla del que suena (s, positivo = atrasado),
        envuelto a ±medio compás. None si no se puede."""
        m = SmartSync._falta_suave(master, pos=pos_m)
        s = SmartSync._falta_suave(slave, pos=pos_s)
        if m is None or s is None:
            return None
        per = s[1]
        e = s[0] - m[0]
        return float(((e + per / 2.0) % per) - per / 2.0)

    @staticmethod
    def match_bpm(master: Deck, slave: Deck):
        bpm_m = master.analysis["bpm"] * master.tempo_rate
        bpm_s_orig = slave.analysis["bpm"]
        if bpm_s_orig <= 0:
            return False
        rate_slave = bpm_m / bpm_s_orig
        slave.set_tempo_from_fader(rate_slave)
        return True

    @staticmethod
    def align_downbeats(master: Deck, slave: Deck):
        err = SmartSync.error_fase_suave(master, slave)
        if err is None:
            err = SmartSync.compute_phase_error(master, slave)
        if err is None:
            return False, "No se pudo calcular la fase."

        SmartSync.saltar_fase(slave, err)
        return True, err

    @staticmethod
    def saltar_fase(slave: Deck, err):
        """Mueve el cursor del entrante `err` segundos (reales) de fase. Si eso lo mandaría antes del
        comienzo del tema (típico al arrancar desde 0:00), salta al siguiente compás en vez de quedarse
        clavado en 0 con el error sin corregir."""
        rate = slave.rate_eff
        delta = int(round(err * rate * slave.sr))
        fs = SmartSync._falta_suave(slave)
        per = int(round(fs[1] * rate * slave.sr)) if fs else 0
        with slave.lock:
            nuevo = slave.cursor + delta
            if nuevo < 0 and per > 0:
                nuevo += per * int(np.ceil(-nuevo / per))
            slave.cursor = int(np.clip(nuevo, 0, len(slave.audio) - 1))
            slave._cursor_frac = 0.0

    @staticmethod
    def preparar_entrada(master: Deck, slave: Deck):
        if not (master.analysis and slave.analysis):
            return False, "Ambos decks deben tener análisis."
        if master.audio is None or slave.audio is None:
            return False, "Ambos decks deben tener audio cargado."
        if master.analysis["bpm"] <= 0 or slave.analysis["bpm"] <= 0:
            return False, "BPM inválido."
        ok, err = SmartSync.align_downbeats(master, slave)
        if not ok:
            return False, err
        bpm_m = master.analysis["bpm"] * master.tempo_rate
        bpm_s_eff = slave.analysis["bpm"] * slave.tempo_rate
        return True, (f"BPM entrante {bpm_s_eff:.2f} = sonando {bpm_m:.2f} | fase alineada ({err*1000.0:+.1f} ms)")


# =====================================================================
# 6) VENTANA PRINCIPAL
# =====================================================================
class AutoMix(QMainWindow):
    def __init__(self):
        super().__init__()
        cfg = leer_config()
        self.punto_a = float(cfg.get("punto_a", DEF_PUNTO_A))
        self.punto_b = float(cfg.get("punto_b", DEF_PUNTO_B))
        self.cruce_ab = bool(cfg.get("cruce_ab", True))
        self._cf_dir = "AB"
        self.carga_auto = True
        self.auto_s = int(cfg.get("auto_s", 30))
        self._fader_prev = None
        self._carga_pendiente = False
        self._mix_pausa_hecha = False
        self._marca_frac = float(cfg.get("marca_frac", -1.0))
        self._marca_disparada = False
        self._ultimo_prog_primario = 0.0
        self._ultimo_deck_primario = None
        self.setWindowTitle("AutoMix Pro 🎚️")
        self.resize(1560, 850)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.split = split
        self.setCentralWidget(split)

        panel_lib = QWidget()
        lib_lay = QVBoxLayout(panel_lib)
        lib_lay.setContentsMargins(8, 8, 0, 8)
        lib_lay.setSpacing(4)
        self.lbl_lib = EtiquetaElidida("📁 Biblioteca — arrastrá carpetas acá")
        lib_lay.addWidget(self.lbl_lib)
        self.ed_filtro = QLineEdit()
        self.ed_filtro.setPlaceholderText("Buscar…")
        self.ed_filtro.setClearButtonEnabled(True)
        lib_lay.addWidget(self.ed_filtro)
        self.biblioteca = Biblioteca()
        lib_lay.addWidget(self.biblioteca, stretch=1)
        lib_btns = QHBoxLayout()
        b_quitar = QPushButton("Quitar"); b_quitar.clicked.connect(self.biblioteca.quitar_seleccion)
        b_limpiar = QPushButton("Vaciar"); b_limpiar.clicked.connect(self.biblioteca.limpiar)
        self.btn_ordenar = QPushButton("🔃 Ordenar por BPM")
        self.btn_ordenar.clicked.connect(self._ordenar_biblioteca_bpm)
        self.btn_reanalizar = QPushButton("🔄 Re-analizar")
        self.btn_reanalizar.setToolTip("Vuelve a analizar el BPM de TODOS los temas de la lista (guía: el BPM del nombre del archivo)")
        self.btn_reanalizar.clicked.connect(self._reanalizar_biblioteca)
        lib_btns.addWidget(b_quitar); lib_btns.addWidget(b_limpiar); lib_btns.addWidget(self.btn_ordenar)
        lib_btns.addWidget(self.btn_reanalizar)
        lib_lay.addLayout(lib_btns)
        lib_lay.addWidget(EtiquetaElidida("Arrastrá un tema a Deck A o B"))
        self.ed_filtro.textChanged.connect(self._filtrar_biblioteca)
        self.biblioteca.cambio.connect(self._biblioteca_cambio)
        self.biblioteca.itemDoubleClicked.connect(self._biblioteca_doble_clic)
        split.addWidget(panel_lib)

        central = QWidget()
        split.addWidget(central)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1)
        split.setSizes([470, 1090])
        split.setChildrenCollapsible(False)
        panel_lib.setMinimumWidth(170)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        decks_row = QHBoxLayout()
        self.deck_a = Deck("A", "#1e3a5f", self._on_analysis)
        self.deck_b = Deck("B", "#5f1e3a", self._on_analysis)
        self.deck_a.on_play_cb = self._auto_sync
        self.deck_b.on_play_cb = self._auto_sync
        # Callback para que el botón reset avise a la ventana y se redibuje el timeline
        self.deck_a.on_reset_cb = self._on_reset_deck
        self.deck_b.on_reset_cb = self._on_reset_deck
        self.panel_cruce = PanelCruce(self)
        decks_row.addWidget(self.deck_a, stretch=1)
        decks_row.addWidget(self.deck_b, stretch=1)
        decks_row.addWidget(self.panel_cruce, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(decks_row)

        self.mixer = GlobalMixer(self.deck_a, self.deck_b, sr=44100, blocksize=1024)
        self.mixer.start()

        cf_row = QHBoxLayout()           # el crossfader va en el panel de la derecha de los deslizadores
        self._cf_row = cf_row
        cf_row.addWidget(QLabel("A"))
        self.crossfader = QSlider(Qt.Orientation.Horizontal)
        self.crossfader.setRange(0, 100)
        self.crossfader.setValue(0)
        self.crossfader.valueChanged.connect(self._update_cf)
        cf_row.addWidget(self.crossfader, stretch=1)
        cf_row.addWidget(QLabel("B"))
        self.sld_master = QSlider(Qt.Orientation.Horizontal)
        self.sld_master.setRange(0, 100)
        self.sld_master.setMinimumWidth(90)
        self.sld_master.setValue(int(leer_config().get("vol_general", 100)))
        self.lbl_master = QLabel(f"{self.sld_master.value()}%")
        self.lbl_master.setMinimumWidth(38)
        self.sld_master.valueChanged.connect(self._vol_general_cambio)
        self.mixer.set_volumen(self.sld_master.value() / 100.0)
        self.mixer._gain_act = self.mixer.gain_obj

        ctrl_box = QGroupBox("🎛️ Controles")
        ctrl_box.setFixedHeight(60)
        c = QHBoxLayout(ctrl_box)
        c.setContentsMargins(8, 4, 8, 4)

        self.btn_mix = QPushButton("🎬 Mezclar (F2)")
        self.btn_mix.setFixedHeight(30)
        self.btn_mix.clicked.connect(self._mix_clicked)
        self.shortcut_f2 = QShortcut(QKeySequence(Qt.Key.Key_F2), self)
        self.shortcut_f2.activated.connect(self._mix_clicked)

        self.shortcut_espacio = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.shortcut_espacio.setContext(Qt.ShortcutContext.WindowShortcut)
        self.shortcut_espacio.activated.connect(self._toggle_play_pausa)

        self.lbl_dur = QLabel("Duración")
        self.spin_mix = QSpinBox()
        self.spin_mix.setRange(1, 120)
        self.spin_mix.setSuffix(" s")
        self.spin_mix.setFixedHeight(30)
        self.spin_mix.setValue(self._cargar_duracion_mezcla())
        self.btn_mix.setText(f"🎬 Mezclar ({self.spin_mix.value()}s) [F2]")
        self.spin_mix.valueChanged.connect(self._duracion_mezcla_cambio)
        c.addStretch()

        contenedor_inferior = QWidget()
        ci_layout = QVBoxLayout(contenedor_inferior)
        ci_layout.setContentsMargins(0, 0, 0, 0)
        ci_layout.setSpacing(6)
        ci_layout.addWidget(self._crear_panel_multibanda())
        root.addWidget(contenedor_inferior)

        self.lbl_status = EtiquetaElidida("Listo con Auto-Gain activado. Espacio = pausa/play.")
        self.lbl_status.setStyleSheet(
            "color:#9fe; background:#111; padding:4px; "
            "border:1px solid #333; border-radius:4px; font-size:11px;"
        )
        self.lbl_status.setFixedHeight(24)
        fila_estado = QHBoxLayout()
        fila_estado.setContentsMargins(0, 0, 0, 0)
        fila_estado.setSpacing(4)
        self.lbl_status.setVisible(False)        # la barra negra de estado ya no se muestra (el texto sigue disponible por tooltip)
        fila_estado.addStretch(1)
        self.btn_consola = QPushButton("🖥")
        self.btn_consola.setCheckable(True)
        self.btn_consola.setFixedSize(34, 24)
        self.btn_consola.setToolTip("Mostrar / ocultar la consola (todo lo que hace el programa, con hora)")
        self.btn_consola.clicked.connect(self._alternar_consola)
        if not CONSOLA.es_windows:
            self.btn_consola.setVisible(False)
        self._f_dur.insertWidget(self._f_dur.count() - 1, self.btn_consola)   # al costado de Duración, mismo tamaño

        barra_box = QGroupBox("⚓ Auto-enganche — progreso del tema sonando")
        barra_box.setFixedHeight(84)
        bl = QHBoxLayout(barra_box)
        bl.setContentsMargins(8, 6, 8, 4)
        bl.setSpacing(8)
        self.barra_prog = BarraProgresoConMarca()
        self.barra_prog.set_marca(self._marca_frac)
        self.barra_prog.marca_cambiada.connect(self._marca_cambiada)
        self.barra_prog.marca_cruzada.connect(self._marca_cruzada)
        bl.addWidget(self.barra_prog, stretch=1)
        self.lbl_marca = QLabel()
        self.lbl_marca.setMinimumWidth(190)
        self.lbl_marca.setStyleSheet("color:#bbb; font-size:11px;")
        self._actualizar_lbl_marca()
        bl.addWidget(self.lbl_marca)
        root.addWidget(barra_box)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Zoom (px/s):"))
        self.sld_zoom = QSlider(Qt.Orientation.Horizontal)
        self.sld_zoom.setRange(5, 300)
        self.sld_zoom.setValue(40)
        self.sld_zoom.valueChanged.connect(self._update_zoom)
        zoom_row.addWidget(self.sld_zoom, stretch=1)
        self.lbl_zoom = QLabel("40")
        self.lbl_zoom.setFixedWidth(50)
        zoom_row.addWidget(self.lbl_zoom)
        root.addLayout(zoom_row)

        tl_box = QGroupBox("🎼 Timeline — Playhead FIJO al centro")
        tl_lay = QVBoxLayout(tl_box)
        tl_lay.setContentsMargins(4, 4, 4, 4)
        self.timeline = UnifiedTimeline(self.deck_a, self.deck_b, on_manito_cb=self._on_manito_release)
        tl_lay.addWidget(self.timeline)
        root.addWidget(tl_box, stretch=1)

        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

        self.mix_timer = QTimer()
        self.mix_timer.timeout.connect(self._mix_step)
        self.mix_steps_total = 0
        self.mix_steps_done = 0
        self.mix_from = 0
        self.mix_to = 0

        self.mix_pausa_timer = QTimer(self)
        self.mix_pausa_timer.setSingleShot(True)
        self.mix_pausa_timer.timeout.connect(self._reanudar_mix)

        self._target_rate_a = None
        self._target_rate_b = None
        self._alpha_a = 0.05
        self._alpha_b = 0.05
        self._smooth_timer = QTimer()
        self._smooth_timer.timeout.connect(self._smooth_tempo)
        self._smooth_timer.start(20)

        self.magnet_on = False
        self._err_filtrado = 0.0
        self._sync_I = 0.0
        self._sync_t = None
        self._sync_n = 0
        self._sync_hist = []
        self.master_for_magnet = None
        self.slave_for_magnet = None
        self.magnet_timer = QTimer()
        self.magnet_timer.timeout.connect(self._magnet_correct)

        self.manito_on = True

        self.biblioteca.cargar()
        self._update_cf()

        self._esc_actual = 1.0
        self._ratio_lista = 470.0 / 1560.0
        self._esc_timer = QTimer(self)
        self._esc_timer.setSingleShot(True)
        self._esc_timer.timeout.connect(self._escalar_segun_ventana)
        self._registrar_escala()
        self.split.splitterMoved.connect(self._splitter_movido)

        # Tamaño "natural" (escala 1.0) = lo que mide el contenido de verdad. La escala sale de
        # comparar la ventana con ese tamaño, así el contenido SIEMPRE entra en la ventana
        # (antes se usaba un 1560x850 fijo y, al agregar paneles, el mínimo pasaba la pantalla).
        self._aplicar_escala(0.6)
        mh = self.minimumSizeHint()
        self.ESC_BASE_W = mh.width() / 0.6 * 1.05      # +5 % de holgura: el mínimo no crece exacto con la escala
        self.ESC_BASE_H = mh.height() / 0.6 * 1.05
        self.resize(mh)
        QTimer.singleShot(0, self._ir_al_minimo)

        self.biblioteca.nuevos.connect(lambda: QTimer.singleShot(1500, self._auto_analizar))
        self.biblioteca.ordenar_por_bpm()                     # al abrir: lista ordenada de menor a mayor BPM
        self._ordenar_al_terminar = True                      # y otra vez cuando termine de analizar lo que falte
        QTimer.singleShot(2500, self._auto_analizar)

    def _crear_panel_multibanda(self):
        cfg = leer_config()
        w = QGroupBox("🎛️ Multibanda Automática y Ecualizador Inteligente")
        g = QGridLayout(w)
        g.setContentsMargins(8, 6, 8, 4)
        g.setVerticalSpacing(3)
        g.setHorizontalSpacing(8)
        naranja = "font-weight: bold; color: #f2a33a;"
        suave = "color: #888;"

        fila = QHBoxLayout()
        self.chk_mb = QCheckBox("Automática (recomendado)")
        self.chk_mb.setChecked(True)          # siempre automático
        self.chk_mb.hide()
        self.chk_mb.setToolTip("Tildada: todo se ajusta solo. Destildada: manual, vos movés Umbral, Ratio y Compensación de cada banda")
        fila.addWidget(self.chk_mb)
        fila.addSpacing(12)
        fila.addWidget(QLabel("Intensidad"))
        self.sld_mb = QSlider(Qt.Orientation.Horizontal)
        self.sld_mb.setRange(0, 100)
        self.sld_mb.setValue(int(cfg.get("mb_int", 60)))
        self.lbl_mb = QLabel(f"{self.sld_mb.value()} %")
        self.lbl_mb.setMinimumWidth(44)
        self.lbl_mb.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fila.addWidget(self.sld_mb, 1); fila.addWidget(self.lbl_mb); fila.addStretch(1)
        col = QVBoxLayout(); col.setSpacing(2); col.addLayout(fila)
        self.lbl_mb_info = EtiquetaElidida("")
        self.lbl_mb_info.setStyleSheet(suave); col.addWidget(self.lbl_mb_info)
        g.addLayout(col, 0, 0, 1, 11)

        columnas = (
            ("Nivel", -60, 0, lambda v: f"{v} dB", "Nivel medio"),
            ("Umbral", -60, 0, lambda v: f"{v} dB", "Umbral"),
            ("Ratio", 10, 30, lambda v: "1:1" if v <= 10 else f"{v / 10:.1f}:1", "Ratio"),
            ("Reducción", 0, 120, lambda v: "0.0 dB" if v == 0 else f"-{v / 10:.1f} dB", "Reducción"),
            ("Compensación", 0, 40, lambda v: f"+{v / 10:.1f} dB", "Compensación"),
        )
        for j, (nombre, _mn, _mx, _f, tip) in enumerate(columnas):
            e = EtiquetaElidida(nombre); e.setStyleSheet(suave); e.setToolTip(tip)
            g.addWidget(e, 1, 1 + 2 * j, 1, 2)
        self.mb_medidores = []
        for i, banda in enumerate(("Graves", "Medios", "Agudos")):
            cab = QLabel(banda); cab.setStyleSheet(naranja); cab.setMinimumWidth(48)
            g.addWidget(cab, 2 + i, 0)
            fila_m = []
            for j, (nombre, mn, mx, fmt, tip) in enumerate(columnas):
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(mn, mx); sl.setValue(mn); sl.setMinimumWidth(50)
                sl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                sl.setFocusPolicy(Qt.FocusPolicy.NoFocus); sl.setToolTip(tip)
                lbl = QLabel(fmt(sl.value())); lbl.setStyleSheet(suave); lbl.setMinimumWidth(48)
                sl.valueChanged.connect(lambda v, l=lbl, f=fmt: l.setText(f(v)))
                g.addWidget(sl, 2 + i, 1 + 2 * j); g.addWidget(lbl, 2 + i, 2 + 2 * j)
                fila_m.append(sl)
            self.mb_medidores.append(fila_m)

        linea = QFrame(); linea.setFrameShape(QFrame.Shape.HLine); linea.setFrameShadow(QFrame.Shadow.Sunken)
        g.addWidget(linea, 5, 0, 1, 11)
        tit = QLabel("Avanzado"); tit.setStyleSheet(naranja)
        g.addWidget(tit, 6, 0, 1, 3)
        def deslizador(fila_g, texto, mn, mx, valor, fmt, tip):
            et = QLabel(texto); et.setToolTip(tip)
            sl = QSlider(Qt.Orientation.Horizontal); sl.setRange(mn, mx); sl.setValue(int(valor)); sl.setToolTip(tip)
            lb = QLabel(fmt(sl.value())); lb.setMinimumWidth(62)
            lb.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            sl.valueChanged.connect(lambda v, l=lb, f=fmt: l.setText(f(v)))
            lb.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            g.addWidget(et, fila_g, 0, 1, 2); g.addWidget(sl, fila_g, 2, 1, 4); g.addWidget(lb, fila_g, 6, 1, 1)
            return sl
        self.sld_lim = deslizador(7, "Máx. corrección", 1, 10, cfg.get("mb_lim", 6), lambda v: f"±{v} dB", "Máx corrección EQ")
        self.sld_vel = deslizador(8, "Velocidad", 1, 40, cfg.get("mb_vel", 20), lambda v: f"{v / 10:.1f} dB/s", "Velocidad EQ")

        self.sld_golpe = deslizador(9, "Golpe 43 Hz", 0, 100, cfg.get("golpe_43", 70), lambda v: "apagado" if v == 0 else f"{v} %",
                                    "Realza el bombo y el bajo (zona de 43 Hz): empujón fijo + extra en el ataque de cada golpe + armónicos para parlantes chicos. 0 % = apagado")
        self.sld_golpe.setStyleSheet("")
        # En manual se mueven Umbral (col 1), Ratio (col 2) y Compensación (col 4) de cada banda.
        man_u = cfg.get("mb_man_umbral", [-18, -16, -14]); man_r = cfg.get("mb_man_ratio", [20, 20, 20]); man_c = cfg.get("mb_man_comp", [0, 0, 0])
        self._mb_pintando = False
        self._mb_manual = False
        for i, fila_m in enumerate(self.mb_medidores):
            for col_i, val in ((1, man_u[i]), (2, man_r[i]), (4, man_c[i])):
                fila_m[col_i].valueChanged.connect(self._mb_manual_cambio)
            fila_m[1].setProperty("man", int(man_u[i])); fila_m[2].setProperty("man", int(man_r[i])); fila_m[4].setProperty("man", int(man_c[i]))
        self.sld_medios = deslizador(10, "Medios (1 kHz)", -100, 60, int(cfg.get("medios_db10", 0)),
                                     lambda v: "0 dB" if v == 0 else f"{v / 10:+.1f} dB",
                                     "Baja (−) o sube (+) los medios con una campana ancha en 1 kHz. Para sacar solo un poquito: probá −1,0 a −2,0 dB. 0 = sin efecto")
        self.sld_agudos = deslizador(11, "Agudos (6 kHz)", -100, 60, int(cfg.get("agudos_db10", 0)),
                                     lambda v: "0 dB" if v == 0 else f"{v / 10:+.1f} dB",
                                     "Baja (−) o sube (+) los agudos (brillo, desde ~6 kHz). Para sacar solo un poquito: probá −1,0 a −2,0 dB. 0 = sin efecto")
        # Mezclar / Duración / Volumen general: a la derecha de los deslizadores (más compacto)
        der = QVBoxLayout(); der.setSpacing(6)
        self.btn_mix.setFixedHeight(34)
        self.btn_mix.setStyleSheet(
            "QPushButton { background:#f5c518; color:#222; font-weight:bold; border:1px solid #b8900a; border-radius:5px; }"
            "QPushButton:hover { background:#ffd83a; }"
            "QPushButton:pressed { background:#d9a800; }"
            "QPushButton:disabled { background:#cfc08a; color:#777; }")
        der.addWidget(self.btn_mix)
        self.spin_mix.setFixedWidth(58)           # corto: solo el número
        f_dur = QHBoxLayout(); f_dur.addWidget(self.lbl_dur); f_dur.addWidget(self.spin_mix)
        f_dur.addSpacing(6)
        f_dur.addStretch(1)
        self._f_dur = f_dur                       # el botón de la consola se agrega acá al lado
        der.addLayout(f_dur)
        f_vol = QHBoxLayout(); f_vol.addWidget(QLabel("🔊 Volumen")); f_vol.addWidget(self.sld_master, 1); f_vol.addWidget(self.lbl_master)
        der.addLayout(f_vol)
        self.crossfader.setToolTip("Crossfader A ↔ B (volumen + BPM compartido)")
        der.addLayout(self._cf_row)
        der.addStretch(1)
        g.addLayout(der, 6, 7, 6, 4)
        self.chk_mb.toggled.connect(self._mb_cambio)
        for sl in (self.sld_mb, self.sld_lim, self.sld_vel, self.sld_golpe, self.sld_medios, self.sld_agudos):
            sl.valueChanged.connect(self._mb_cambio)
        self._mb_cambio()
        return w

    def _mb_modo_manual(self, manual):
        """Habilita/deshabilita los deslizadores que se mueven a mano y ajusta sus rangos."""
        if manual == self._mb_manual:
            return
        self._mb_manual = manual
        self._mb_pintando = True
        try:
            for i, fila_m in enumerate(self.mb_medidores):
                for col_i, (mn, mx) in ((1, (-60, 0)), (2, (10, 80)), (4, (0, 120))):
                    sl = fila_m[col_i]
                    sl.setRange(mn, mx)
                    sl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not manual)
                    sl.setFocusPolicy(Qt.FocusPolicy.StrongFocus if manual else Qt.FocusPolicy.NoFocus)
                    if manual:
                        sl.setValue(int(sl.property("man")))
        finally:
            self._mb_pintando = False
        if not manual:
            for fila_m in self.mb_medidores:
                fila_m[2].setRange(10, 30); fila_m[4].setRange(0, 40)
        self.lbl_mb_info.setText("Manual: movés Umbral, Ratio y Compensación de cada banda · cruces fijos 150 Hz / 2,5 kHz" if manual
                                 else "Cruces fijos: 150 Hz / 2,5 kHz · los valores de abajo se mueven solos, en vivo")

    def _mb_manual_cambio(self, *_):
        if self._mb_pintando or not self._mb_manual:
            return
        mb = self.mixer.mb.mb
        for i, fila_m in enumerate(self.mb_medidores):
            u, r, c = fila_m[1].value(), fila_m[2].value(), fila_m[4].value()
            fila_m[1].setProperty("man", u); fila_m[2].setProperty("man", r); fila_m[4].setProperty("man", c)
            mb.man_umbral[i] = float(u); mb.man_ratio[i] = r / 10.0; mb.man_comp[i] = c / 10.0
        guardar_config(mb_man_umbral=[int(f[1].value()) for f in self.mb_medidores],
                       mb_man_ratio=[int(f[2].value()) for f in self.mb_medidores],
                       mb_man_comp=[int(f[4].value()) for f in self.mb_medidores])

    def _mb_cambio(self, *_):
        self.lbl_mb.setText(f"{self.sld_mb.value()} %")
        mb = self.mixer.mb
        mb.intensidad = self.sld_mb.value() / 100.0
        mb.eq.limite = float(self.sld_lim.value())
        mb.eq.velocidad = self.sld_vel.value() / 10.0
        manual = not self.chk_mb.isChecked()
        self._mb_modo_manual(manual)
        mb.mb.manual = manual
        if manual:
            self._mb_manual_cambio()
        self.sld_mb.setEnabled(not manual); self.sld_lim.setEnabled(not manual); self.sld_vel.setEnabled(not manual)
        self.mixer.mb_activo = True
        self.mixer.golpe.cantidad = self.sld_golpe.value() / 100.0
        self.mixer.medios.db = self.sld_medios.value() / 10.0
        self.mixer.agudos.db = self.sld_agudos.value() / 10.0
        guardar_config(medios_db10=int(self.sld_medios.value()), agudos_db10=int(self.sld_agudos.value()), mb_auto=self.chk_mb.isChecked(),
                       mb_int=int(self.sld_mb.value()),
                       mb_lim=int(self.sld_lim.value()), mb_vel=int(self.sld_vel.value()),
                       golpe_43=int(self.sld_golpe.value()))

    def _mb_actualizar_barras(self):
        mb = self.mixer.mb.mb
        act = self.mixer.mb_activo
        for i, fila in enumerate(self.mb_medidores):
            vals = (mb.niveles[i], mb.umbral[i], mb.ratio[i] * 10.0, mb.reduccion[i] * 10.0, mb._mk[i] * 10.0) \
                if act else (-60, -60, 10, 0, 0)
            self._mb_pintando = True
            try:
                for j, (sl, v) in enumerate(zip(fila, vals)):
                    if self._mb_manual and j in (1, 2, 4):      # en manual esos los mueve el usuario
                        continue
                    sl.setValue(int(round(float(v))))
            finally:
                self._mb_pintando = False

    def _vol_general_cambio(self, v):
        self.lbl_master.setText(f"{v}%")
        self.mixer.set_volumen(v / 100.0)
        guardar_config(vol_general=int(v))

    def _cargar_duracion_mezcla(self):
        try:
            return max(1, min(120, int(leer_config().get("mezcla_s", 10))))
        except Exception:
            return 10

    def _duracion_mezcla_cambio(self, v):
        self.btn_mix.setText(f"🎬 Mezclar ({v}s) [F2]")
        guardar_config(mezcla_s=int(v))

    def set_forma_cruce(self, pa, pb, activo):
        self.punto_a, self.punto_b, self.cruce_ab = float(pa), float(pb), bool(activo)
        guardar_config(punto_a=self.punto_a, punto_b=self.punto_b, cruce_ab=self.cruce_ab)
        self._update_cf()

    def _auto_s_cambio(self, v):
        self.auto_s = int(v)
        guardar_config(auto_s=self.auto_s)

    def _programar_carga(self, detenido):
        if not self.carga_auto:
            return
        if self._carga_pendiente:
            return
        self._carga_pendiente = True
        def _run():
            self._carga_pendiente = False
            self._cargar_siguiente(detenido)
        QTimer.singleShot(400, _run)

    def _siguiente_en_biblioteca(self, path_actual):
        rutas = self.biblioteca.todas()
        clave = os.path.normcase(os.path.abspath(path_actual)) if path_actual else None
        for i, r in enumerate(rutas):
            if os.path.normcase(os.path.abspath(r)) == clave:
                for j in range(i + 1, len(rutas)):
                    if os.path.isfile(rutas[j]):
                        return rutas[j], None
                if rutas:
                    for j in range(len(rutas)):
                        if os.path.isfile(rutas[j]):
                            return rutas[j], None
                return None, "fin de la biblioteca"
        for r in rutas:
            if os.path.isfile(r):
                return r, None
        return None, "biblioteca vacía"

    def _cargar_siguiente(self, destino):
        if not self.carga_auto:
            return
        otro = self.deck_a if destino is self.deck_b else self.deck_b
        if not otro.path:          # el otro deck está vacío (p. ej. al iniciar): no cargar nada solo
            return
        referencia_path = otro.path
        ruta, motivo = self._siguiente_en_biblioteca(referencia_path)
        if ruta is None:
            self._set_status(f"🔁 Carga automática: {motivo}")
            return
        destino.load_track(ruta)
        self._set_status(f"🔁 Deck {destino.name} en espera: {os.path.basename(ruta)}")

    def _auto_vigilar(self):
        if not self.carga_auto or self.mix_timer.isActive() or self.mix_pausa_timer.isActive():
            return
        f = self.crossfader.value()
        if f not in (0, 100):
            return
        sonando = self.deck_a if f == 0 else self.deck_b
        espera = self.deck_b if f == 0 else self.deck_a
        if not sonando.playing or sonando.audio is None or espera.playing:
            return
        if espera.audio is None or not espera.analysis:
            return
        resta = (len(sonando.audio) - sonando.cursor) / (sonando.sr * max(1e-6, sonando.rate_eff))
        if resta <= max(float(self.auto_s), self.spin_mix.value() + 4.0):   # +3 s de pausa al 50 % +1 s de margen
            self._set_status(f"🔁 Mezcla automática hacia el Deck {espera.name}")
            self._mix_clicked()

    _analizador_bib = None
    _fallidos = None
    _ordenar_al_terminar = False

    def _analisis_en_curso(self):
        return self._analizador_bib is not None and self._analizador_bib.isRunning()

    def _iniciar_analisis(self, rutas, forzar, fin, texto):
        self.biblioteca.marcar(rutas)
        a = AnalizadorBiblioteca(rutas, forzar=forzar)
        _mantener_vivo(a)
        a.progreso.connect(lambda i, t: self._set_status(f"{texto}: {i}/{t}"))
        a.tema_listo.connect(self.biblioteca.quitar_de_cola)
        a.terminado.connect(fin)
        self._analizador_bib = a
        a.start()

    def _pendientes(self):
        if self._fallidos is None:
            self._fallidos = set()
        return [r for r in self.biblioteca.temas_sin_bpm()
                if self.biblioteca._clave(r) not in self._fallidos and os.path.isfile(r)]

    def _auto_analizar(self):
        """Los temas nuevos de la lista se analizan solos (se ven con ⏳ hasta que terminan)."""
        if self._analisis_en_curso():
            return
        faltan = self._pendientes()
        if not faltan:
            self._ordenar_al_terminar = False
            return
        self._set_status(f"⏳ Analizando {len(faltan)} temas (BPM)…")
        self._iniciar_analisis(faltan, False, self._fin_analisis, "⏳ Analizando BPM")

    def _fin_analisis(self):
        self.biblioteca.marcar(())
        if self._fallidos is None:
            self._fallidos = set()
        for r in self.biblioteca.temas_sin_bpm():            # los que no se pudieron analizar no se reintentan en bucle
            self._fallidos.add(self.biblioteca._clave(r))
        if self._ordenar_al_terminar:
            self._ordenar_al_terminar = False
            self.biblioteca.ordenar_por_bpm()
            self._set_status("✅ Biblioteca ordenada por BPM")
        else:
            self._set_status("✅ Lista analizada")
        QTimer.singleShot(300, self._auto_analizar)           # por si se agregaron temas mientras tanto

    def _ordenar_biblioteca_bpm(self):
        self.biblioteca.ordenar_por_bpm()                     # ya: primero los que tienen BPM conocido
        self._fallidos = set()                                # un clic explícito vuelve a intentar los que fallaron
        faltan = self._pendientes()
        if not faltan:
            self._set_status("✅ Biblioteca ordenada por BPM")
            return
        self._ordenar_al_terminar = True
        if self._analisis_en_curso():
            self._set_status("⏳ Analizando la lista… se ordena sola al terminar")
            return
        self._set_status(f"⏳ Analizando {len(faltan)} temas (BPM)…")
        self._iniciar_analisis(faltan, False, self._fin_analisis, "⏳ Analizando BPM")

    def _reanalizar_biblioteca(self):
        if self._analizador_bib is not None and self._analizador_bib.isRunning():
            if self._analizador_bib.forzar:                       # segundo clic = cancelar
                self._analizador_bib.cancelar = True
                self._set_status("⏹ Cancelando re-análisis…")
            else:
                self._set_status("⏳ Analizando biblioteca…")
            return
        rutas = self.biblioteca.todas()
        if not rutas:
            self._set_status("La lista está vacía")
            return
        self._set_status(f"🔄 Re-analizando {len(rutas)} temas… (clic otra vez en el botón para cancelar)")
        self.btn_reanalizar.setText("⏹ Cancelar")
        self._iniciar_analisis(rutas, True, self._fin_reanalisis, "🔄 Re-analizando BPM")

    def _fin_reanalisis(self):
        self.biblioteca.marcar(())
        cancelado = bool(self._analizador_bib and self._analizador_bib.cancelar)
        self.btn_reanalizar.setText("🔄 Re-analizar")
        self._set_status("⏹ Re-análisis cancelado" if cancelado else
                         "✅ Lista re-analizada. Si un tema ya estaba cargado en un deck, volvé a cargarlo para usar el BPM nuevo")

    ESC_BASE_W = 1560.0
    ESC_BASE_H = 850.0

    def _registrar_escala(self):
        MAX = 16777215
        self._esc_fuentes = []
        for wd in [self] + self.findChildren(QWidget):
            if wd is self.biblioteca or self.biblioteca.isAncestorOf(wd):
                continue
            fb = wd.font()
            if fb.pointSizeF() > 0:
                self._esc_fuentes.append((wd, fb, fb.pointSizeF(), 0))
            elif fb.pixelSize() > 0:
                self._esc_fuentes.append((wd, fb, 0.0, fb.pixelSize()))
        self._esc_widgets = []
        for wd in self.findChildren(QWidget):
            if isinstance(wd, QScrollBar):
                continue
            p = wd.parentWidget()
            if isinstance(p, QAbstractScrollArea) and wd is p.viewport():
                continue
            mn, mx, ss = wd.minimumSize(), wd.maximumSize(), wd.styleSheet()
            if mn.width() or mn.height() or mx.width() < MAX or mx.height() < MAX or "font-size" in ss:
                self._esc_widgets.append((wd, mn.width(), mn.height(), mx.width(), mx.height(), ss))
        self._esc_layouts = []
        for lay in self.findChildren(QLayout):
            m = lay.contentsMargins()
            self._esc_layouts.append((lay, m.left(), m.top(), m.right(), m.bottom(), lay.spacing()))

    def _ir_al_minimo(self):
        self.resize(self.minimumSizeHint())
        self._escalar_segun_ventana()
        # al iniciar, la lista de temas es el doble de ancha (la ventana crece lo mismo que la lista)
        lw = self.split.sizes()[0]
        if lw > 0:
            self.resize(self.width() + lw, self.height())
            self._ratio_lista = (2.0 * lw) / float(self.width())
            self._escalar_segun_ventana()
        self._ajustar_a_pantalla()

    def _ajustar_a_pantalla(self):
        """Al iniciar: que la ventana entre en la pantalla (barra de tareas incluida), centrada, con el
        contenido re-escalado y el timeline redibujado con su tamaño final."""
        try:
            scr = self.screen() or QApplication.primaryScreen()
            ag = scr.availableGeometry()
            fg, g = self.frameGeometry(), self.geometry()
            marco_w, marco_h = fg.width() - g.width(), fg.height() - g.height()
            w = min(self.width(), ag.width() - marco_w)
            h = min(self.height(), ag.height() - marco_h)
            self.resize(w, h)
            self.move(ag.left() + (ag.width() - (w + marco_w)) // 2,
                      ag.top() + (ag.height() - (h + marco_h)) // 2)
        except Exception:
            pass
        self._escalar_segun_ventana()
        QTimer.singleShot(0, self._redibujar_timeline_inicial)
        QTimer.singleShot(250, self._redibujar_timeline_inicial)

    def _redibujar_timeline_inicial(self):
        try:
            self.timeline.redraw()
        except Exception:
            pass

    def _splitter_movido(self, *_):
        tot = sum(self.split.sizes())
        if tot > 0:
            self._ratio_lista = self.split.sizes()[0] / tot

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "_esc_timer"):
            self._esc_timer.start(30)

    def _escalar_segun_ventana(self):
        s = min(self.width() / self.ESC_BASE_W, self.height() / self.ESC_BASE_H)
        s = max(0.6, min(1.6, int(s * 50) / 50.0))      # hacia abajo: nunca más grande que la ventana
        if abs(s - self._esc_actual) > 1e-9:
            self._aplicar_escala(s)
        tot = sum(self.split.sizes())
        if tot > 0:
            a = int(round(tot * self._ratio_lista))
            self.split.setSizes([a, tot - a])

    def _aplicar_escala(self, s):
        MAX = 16777215
        global UI_ESCALA
        self._esc_actual = s; UI_ESCALA = s
        for wd, fb, pt, px in self._esc_fuentes:
            try:
                nf = QFont(fb)
                if pt > 0: nf.setPointSizeF(max(5.0, pt * s))
                else: nf.setPixelSize(max(6, int(round(px * s))))
                wd.setFont(nf)
            except RuntimeError:
                pass
        r = lambda v: int(round(v * s))
        for wd, minw, minh, maxw, maxh, ss in self._esc_widgets:
            try:
                wd.setMinimumSize(r(minw), r(minh))
                wd.setMaximumSize(maxw if maxw >= MAX else r(maxw), maxh if maxh >= MAX else r(maxh))
                if "font-size" in ss:
                    nuevo = re.sub(r"font-size:\s*(\d+(?:\.\d+)?)px", lambda m: f"font-size:{max(6, r(float(m.group(1))))}px", ss)
                    if nuevo != wd.styleSheet(): wd.setStyleSheet(nuevo)
            except RuntimeError:
                pass
        for lay, l, t, ri, b, sp in self._esc_layouts:
            try:
                lay.setContentsMargins(r(l), r(t), r(ri), r(b))
                if sp >= 0: lay.setSpacing(r(sp))
            except RuntimeError:
                pass

    def _filtrar_biblioteca(self, txt):
        t = txt.strip().lower()
        for i in range(self.biblioteca.count()):
            it = self.biblioteca.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _biblioteca_cambio(self):
        self.lbl_lib.setText(f"📁 Biblioteca ({self.biblioteca.count()})")
        self.biblioteca.guardar()

    def _biblioteca_doble_clic(self, it):
        p = it.data(Qt.ItemDataRole.UserRole)
        if not os.path.isfile(p): return
        if self.deck_a.playing and self.deck_b.playing:
            self._set_status("Los dos decks están sonando.")
            return
        (self.deck_b if self.deck_a.playing else self.deck_a).load_track(p)

    def _alternar_consola(self):
        visible = CONSOLA.alternar()
        self.btn_consola.setChecked(visible)
        if CONSOLA._modo == "terminal":
            self._set_status("🖥 Lo abriste desde una terminal: ahí mismo ves todo lo que hace")
            return
        self._set_status("🖥 Consola abierta (se cierra con este mismo botón)" if visible else "🖥 Consola oculta")

    def _set_status(self, text):
        self.lbl_status.setText(text)
        try:
            self.btn_consola.setToolTip(f"{text}\n\nMostrar / ocultar la consola (todo lo que hace el programa, con hora)")
        except Exception:
            pass

    def _on_analysis(self, deck, res):
        self.timeline.redraw()
        try:
            self._apply_shared_bpm(self.crossfader.value() / 100.0)
        except Exception:
            import traceback; traceback.print_exc()
        try:                                  # el análisis llegó con el tema ya sonando: se empareja ahora mismo
            d = deck if isinstance(deck, Deck) else (self.deck_a if deck == "A" else self.deck_b)   # llega el nombre ("A"/"B")
            otro = self.deck_b if d is self.deck_a else self.deck_a
            if d.playing and otro.playing and not self.magnet_on and d.analysis and otro.analysis:
                self._auto_sync(d)
                self._alinear_ya(d)
        except Exception:
            import traceback; traceback.print_exc()

    def _on_reset_deck(self, deck):
        """Callback que dispara el Deck al hacer reset. Redibuja el timeline
        y muestra un mensaje de status para dar feedback visual."""
        try:
            self.timeline.redraw()
        except Exception:
            pass
        if deck is self.deck_a: self._target_rate_a = None
        else: self._target_rate_b = None
        self._set_status(f"⟲ Deck {deck.name}: tempo al 100 %")

    def _update_zoom(self):
        v = self.sld_zoom.value()
        self.lbl_zoom.setText(str(v))
        self.timeline.set_zoom_px(float(v))

    def _smooth_tempo(self):
        for attr_t, attr_al, deck in (("_target_rate_a", "_alpha_a", self.deck_a),
                                      ("_target_rate_b", "_alpha_b", self.deck_b)):
            target = getattr(self, attr_t)
            if target is None: continue
            if self.magnet_on and deck is self.slave_for_magnet:      # lo maneja el sync, sin retraso
                setattr(self, attr_t, None); continue
            alpha = getattr(self, attr_al)
            cur = deck.tempo_rate
            new = cur + (target - cur) * alpha
            if abs(target - new) < 1e-5:
                new = target
                setattr(self, attr_t, None)
                setattr(self, attr_al, 0.05)
            if new != cur:
                deck.tempo_rate = new
                deck._update_bpm_label()

    def _update_cf(self):
        fader_val = self.crossfader.value()
        fader_cambio = (self._fader_prev != fader_val)
        self._fader_prev = fader_val

        x = fader_val / 100.0

        if fader_val == 0: self._cf_dir = "AB"
        elif fader_val == 100: self._cf_dir = "BA"

        if self.cruce_ab:
            t = x if self._cf_dir == "AB" else 1.0 - x
            v_sale, v_entra = perfil_cruce_ab(t, self.punto_a, self.punto_b)
            gan_a, gan_b = (v_sale, v_entra) if self._cf_dir == "AB" else (v_entra, v_sale)
        else:
            tramo = max(1e-6, 1.0 - CF_BAJA_DESDE)
            gan_a = min(1.0, max(0.0, (1.0 - x) / tramo))
            gan_b = min(1.0, max(0.0, x / tramo))

        self.deck_a.volume = gan_a * (self.deck_a.sld_vol.value() / 100.0)
        self.deck_b.volume = gan_b * (self.deck_b.sld_vol.value() / 100.0)

        self._apply_shared_bpm(x)

        if fader_val == 0 and self.deck_a.original_bpm:
            self._target_rate_a = 1.0
            self._alpha_a = 0.05
        elif fader_val == 100 and self.deck_b.original_bpm:
            self._target_rate_b = 1.0
            self._alpha_b = 0.05

        if not fader_cambio:
            return

        if fader_val == 0:
            if self.deck_b.playing:
                self.deck_b.stop()
                self._set_status("🛑 Deck B detenido")
            self._programar_carga(self.deck_b)
        elif fader_val == 100:
            if self.deck_a.playing:
                self.deck_a.stop()
                self._set_status("🛑 Deck A detenido")
            self._programar_carga(self.deck_a)

    BPM_RATIO_MAX = 1.22      # más distancia que esta entre los dos temas: no se estiran (sonarían acelerados/graves)

    def _bpm_compatibles(self):
        a, b = self.deck_a.original_bpm, self.deck_b.original_bpm
        if not (a and b):
            return True
        return max(a, b) / min(a, b) <= self.BPM_RATIO_MAX

    def _apply_shared_bpm(self, x):
        bpm_a0 = self.deck_a.original_bpm
        bpm_b0 = self.deck_b.original_bpm
        if not (bpm_a0 and bpm_b0):
            return
        if not self._bpm_compatibles():
            self._target_rate_a = self._target_rate_b = 1.0       # cada tema a su velocidad natural
            self._alpha_a = self._alpha_b = 0.05
            return

        target_bpm_a = bpm_a0 + (bpm_b0 - bpm_a0) * x
        target_bpm_b = bpm_a0 + (bpm_b0 - bpm_a0) * x

        self._target_rate_a = float(np.clip(target_bpm_a / bpm_a0, 0.5, 2.0))
        self._target_rate_b = float(np.clip(target_bpm_b / bpm_b0, 0.5, 2.0))
        self._alpha_a = self._alpha_b = 0.05

    def _auto_sync(self, deck):
        otro = self.deck_b if deck is self.deck_a else self.deck_a
        if not otro.playing:
            if self.magnet_on and self.master_for_magnet is deck:
                self._soltar_sync(None)
            return
        master, slave = otro, deck
        if not (master.original_bpm and slave.original_bpm):
            return
        slave.trim = 1.0
        self._err_filtrado = 0.0
        self._sync_I = 0.0; self._sync_t = None; self._sync_hist = []
        if not self._bpm_compatibles():
            slave.set_tempo_from_fader(1.0)
            self._target_rate_a = self._target_rate_b = None
            if self.magnet_on:
                self._soltar_sync(None)
            SmartSync.align_downbeats(master, slave)
            self._set_status(f"↔ BPM muy distintos ({master.original_bpm:.0f} y {slave.original_bpm:.0f}): "
                             f"cada tema mantiene su velocidad (sin estirar)")
            return
        bpm_maestro = master.original_bpm * master.rate_eff
        rate_slave = float(np.clip(bpm_maestro / slave.original_bpm, 0.5, 2.0))
        slave.set_tempo_from_fader(rate_slave)
        self._target_rate_a = self._target_rate_b = None

        ok, msg = SmartSync.preparar_entrada(master, slave)
        self.timeline.redraw()
        self._set_status(("🔗 " if ok else "⚠️ ") + f"{slave.name}→{master.name}: " + msg)
        if ok:
            self.master_for_magnet = master
            self.slave_for_magnet = slave
            self.magnet_on = True
            if not self.magnet_timer.isActive():
                self.magnet_timer.start(25)
            slave_playing_antes = slave.playing
            slave.playing = True
            try:
                self._apply_shared_bpm(self.crossfader.value() / 100.0)
            finally:
                slave.playing = slave_playing_antes

    # Control de fase PI: el entrante SIGUE exactamente el tempo del que suena (sin retraso) y solo
    # se le suma un microajuste de velocidad para cerrar el error de fase. NUNCA salta mientras se oye.
    SYNC_KP = 1.0               # (1/s)
    SYNC_KI = 0.20              # (1/s²)
    SYNC_TRIM_MAX = 0.025
    SYNC_SLEW = 0.0006          # cambio máximo del microajuste por tick de 25 ms
    SYNC_SALTO_S = 0.012        # salto de fase solo si el entrante está en silencio y el error supera esto
    SYNC_VOL_SILENCIO = 0.02

    def _magnet_correct(self):
        if not self.magnet_on: return
        master = self.master_for_magnet
        slave = self.slave_for_magnet
        if master is None or slave is None: return
        if not master.playing:
            self._soltar_sync(slave); return
        if not slave.playing:
            slave.trim = 1.0
            self._soltar_sync(master); return

        ahora = time.monotonic()
        dt = 0.025 if self._sync_t is None else float(np.clip(ahora - self._sync_t, 0.005, 0.1))
        self._sync_t = ahora

        # 1) velocidad base: exactamente el BPM del que suena (si él se mueve, el entrante lo acompaña al instante)
        if master.original_bpm and slave.original_bpm and self._bpm_compatibles():
            base = float(np.clip(master.original_bpm * master.rate_eff / slave.original_bpm, 0.5, 2.0))
            slave.tempo_rate = base
            self._sync_n += 1
            if self._sync_n % 8 == 0:
                slave.set_tempo_from_fader(base)            # refresca slider y etiqueta
        else:
            return

        # 2) error de fase (mediana de los últimos 5: descarta el pico de 1 bloque de audio entre los dos decks)
        snap = self.mixer.snap_pos            # posiciones de ambos decks en el mismo instante (sin picos de 1 bloque)
        if snap is not None:
            pm, ps = (snap[0], snap[1]) if master is self.deck_a else (snap[1], snap[0])
        else:
            pm = ps = None
        e_raw = SmartSync.error_fase_suave(master, slave, pm, ps)
        if e_raw is None: return
        self._sync_hist.append(e_raw)
        if len(self._sync_hist) > 5:
            self._sync_hist.pop(0)
        e = float(np.median(self._sync_hist))

        # 3) en silencio se puede saltar sin que se note; sonando, jamás
        if slave.volume < self.SYNC_VOL_SILENCIO and abs(e) > self.SYNC_SALTO_S and len(self._sync_hist) >= 5:
            SmartSync.saltar_fase(slave, e)
            slave.trim = 1.0
            self._sync_I = 0.0
            self._sync_hist = []
            return

        # 4) PI sobre la velocidad (siempre hacia adelante, cambios suaves)
        self._sync_I = float(np.clip(self._sync_I + self.SYNC_KI * e * dt, -0.01, 0.01))
        objetivo = 1.0 + float(np.clip(self.SYNC_KP * e + self._sync_I, -self.SYNC_TRIM_MAX, self.SYNC_TRIM_MAX))
        slave.trim += float(np.clip(objetivo - slave.trim, -self.SYNC_SLEW, self.SYNC_SLEW))
        self._err_filtrado = e
        if self._sync_n % 80 == 0:
            print(f"[sync] {slave.name}→{master.name} error {e*1000:+.1f} ms | trim {slave.trim:.4f} | I {self._sync_I:+.4f} | vol {slave.volume:.2f}")

    def _vigilar_sync(self):
        """Red de seguridad: si suenan los dos decks, hay grilla en ambos y el sync no está activo, se empareja."""
        a, b = self.deck_a, self.deck_b
        if self.magnet_on or not (a.playing and b.playing and a.analysis and b.analysis):
            return
        t = time.monotonic()
        if t - getattr(self, "_t_vig_sync", 0.0) < 1.5:
            return
        self._t_vig_sync = t
        if self.mix_timer.isActive() or self.mix_pausa_timer.isActive():
            entra = b if self.mix_to == 100 else a
        else:
            entra = b if a.volume >= b.volume else a
        print(f"[sync] el sync no estaba activo con los dos decks sonando: se empareja el Deck {entra.name}")
        self._auto_sync(entra)
        self._alinear_ya(entra)

    def _alinear_ya(self, entra):
        """Salto de fase inmediato del entrante contra el que suena (primer downbeat), sin esperar al PI.
        Así la mezcla arranca con error ~0 y el ajuste fino solo mantiene."""
        sale = self.deck_a if entra is self.deck_b else self.deck_b
        if not (sale.playing and entra.playing and sale.analysis and entra.analysis):
            return
        if not self._bpm_compatibles():
            return
        snap = None
        ok, err = SmartSync.align_downbeats(sale, entra)
        if ok:
            entra.trim = 1.0
            self._sync_I = 0.0; self._sync_hist = []; self._sync_t = None
            self.master_for_magnet, self.slave_for_magnet = sale, entra
            self.magnet_on = True
            if not self.magnet_timer.isActive():
                self.magnet_timer.start(25)

    def _soltar_sync(self, quedo):
        self.magnet_on = False
        self.magnet_timer.stop()
        if quedo is None: return
        quedo.tempo_rate = float(np.clip(quedo.tempo_rate * quedo.trim, 0.5, 2.0))   # mismo rate_eff: sin escalón
        quedo.trim = 1.0
        if quedo.playing and abs(quedo.tempo_rate - 1.0) > 1e-4:
            if quedo is self.deck_a:
                self._target_rate_a, self._alpha_a = 1.0, 0.01
            else:
                self._target_rate_b, self._alpha_b = 1.0, 0.01
            self._set_status("🔗 Sync suelto: velocidad normal")

    # ================= MEZCLA CON PAUSA AL 50% =================
    def _mix_clicked(self):
        if self.mix_pausa_timer.isActive():          # en la pausa del 50 %: seguir ya, sin invertir el sentido
            self.mix_pausa_timer.stop()
            self._reanudar_mix()
            return
        if self.mix_timer.isActive():                # ya hay una mezcla en curso: no reiniciarla
            return
        current = self.crossfader.value()
        if current <= 50:
            target = 100
            direction = "A → B"
        else:
            target = 0
            direction = "B → A"

        entra = self.deck_b if target == 100 else self.deck_a
        if entra.audio is None:
            self._set_status(f"⚠️ Cargá un tema en Deck {entra.name}")
            return
        if not entra.analysis:               # sin grilla no se puede emparejar: se espera a que termine el análisis
            n = getattr(self, "_mix_espera_n", 0)
            if n < 360:                      # hasta ~90 s
                if n == 0:
                    self._mix_esperando = True
                self._mix_espera_n = n + 1
                self._set_status(f"⏳ Esperando el análisis del Deck {entra.name} para mezclar emparejado…")
                QTimer.singleShot(250, self._mix_clicked)
                return
        self._mix_espera_n = 0
        self._mix_esperando = False
        if not entra.playing:
            entra.play()                     # al arrancar, _auto_sync ya lo alinea
        else:
            self._auto_sync(entra)           # ya sonaba (en espera): al empezar la mezcla se alinea A LA FUERZA
        self._alinear_ya(entra)              # y se confirma con el primer downbeat, antes de que se escuche

        self._cf_dir = "AB" if target == 100 else "BA"
        self.mix_from = current
        self.mix_to = target

        duration_s = float(self.spin_mix.value())
        interval_ms = 50
        self.mix_steps_total = int(duration_s * (1000.0 / interval_ms))
        self.mix_steps_done = 0
        self._mix_pausa_hecha = False
        self.mix_pausa_timer.stop()

        self.mix_timer.start(interval_ms)
        self._set_status(f"🎬 Mezclando {direction} en {int(duration_s)} s...")

    def _mix_step(self):
        if self.mix_steps_done >= self.mix_steps_total:
            self.mix_timer.stop()
            self.crossfader.setValue(self.mix_to)
            self._set_status("🎬 Mezcla completada")
            return

        self.mix_steps_done += 1
        frac = self.mix_steps_done / self.mix_steps_total
        value = int(round(self.mix_from + (self.mix_to - self.mix_from) * frac))

        if not self._mix_pausa_hecha:
            prev = self.crossfader.value()
            cruzando = (prev < 50 <= value) or (prev > 50 >= value)
            if cruzando:
                self.crossfader.setValue(50)
                self._mix_pausa_hecha = True
                self.mix_timer.stop()
                self._set_status("⏸ Mezcla pausada 3 s en el 50%…")
                self.mix_pausa_timer.start(3000)
                return

        self.crossfader.setValue(value)

    def _reanudar_mix(self):
        if self.mix_steps_done < self.mix_steps_total:
            self._set_status("🎬 Mezcla reanudada")
            self.mix_timer.start(50)

    # ================= PAUSA/PLAY CON ESPACIO =================
    def _toggle_play_pausa(self):
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QSpinBox)):
            return
        prim = self._deck_primario()
        if prim is None or prim.audio is None:
            self._set_status("▶ No hay deck cargado para pausar/reanudar")
            return
        if prim.playing:
            prim.pause()
            self._set_status(f"⏸ Deck {prim.name} pausado (Espacio)")
        else:
            prim.play()
            self._set_status(f"▶ Deck {prim.name} reanudado (Espacio)")

    # ================= AUTO-ENGANCHE =================
    def _deck_primario(self):
        a, b = self.deck_a, self.deck_b
        a_ok = a.playing and a.audio is not None
        b_ok = b.playing and b.audio is not None
        if a_ok and b_ok:
            return a if self.crossfader.value() < 50 else b
        if a_ok: return a
        if b_ok: return b
        f = self.crossfader.value()
        if f < 50 and a.audio is not None:
            return a
        if f >= 50 and b.audio is not None:
            return b
        if a.audio is not None: return a
        if b.audio is not None: return b
        return None

    def _marca_cambiada(self, f):
        self._marca_frac = float(f)
        self._marca_disparada = False
        prim = self._deck_primario()
        if prim is not None and prim.analysis and prim.analysis.get("duration", 0) > 0:
            self._ultimo_prog_primario = prim.position_seconds() / prim.analysis["duration"]
        else:
            self._ultimo_prog_primario = 0.0
        guardar_config(marca_frac=self._marca_frac)
        self._actualizar_lbl_marca()

    def _marca_cruzada(self, f):
        pass

    def _actualizar_lbl_marca(self):
        if not hasattr(self, "lbl_marca"):
            return
        if self._marca_frac < 0:
            self.lbl_marca.setText("Sin marca — clic sobre la barra\n(doble clic para borrar)")
        else:
            self.lbl_marca.setText(f"⚓ Marca: {self._marca_frac * 100:.1f}%\nDoble clic para borrar")

    def _tick_auto_enganche(self):
        prim = self._deck_primario()

        if prim is not self._ultimo_deck_primario:
            self._ultimo_deck_primario = prim
            self._marca_disparada = False
            self._ultimo_prog_primario = 0.0

        if prim is None or not prim.analysis or prim.analysis.get("duration", 0) <= 0:
            self.barra_prog.set_progreso(0.0, 0.0, 0.0)
            return

        dur = float(prim.analysis["duration"])
        seg = float(prim.position_seconds())
        prog = max(0.0, min(1.0, seg / dur if dur > 0 else 0.0))

        self.barra_prog.set_progreso(prog, seg, dur)

        if self._marca_frac >= 0 and not self._marca_disparada:
            if self._ultimo_prog_primario < self._marca_frac <= prog:
                self._marca_disparada = True
                self._set_status(
                    f"⚓ Auto-enganche disparado (marca {self._marca_frac * 100:.1f}%) → mezcla"
                )
                try:
                    self._mix_clicked()
                except Exception:
                    import traceback; traceback.print_exc()

        self._ultimo_prog_primario = prog

    def _on_manito_release(self, deck):
        anchor = self.timeline.anchor_a if deck == "A" else self.timeline.anchor_b
        self._set_status(f"✋ Deck {deck} movido a {fmt_time(anchor)}")

    def _tick(self):
        self.deck_a.tick()
        self.deck_b.tick()
        self._mb_actualizar_barras()
        rutas = (self.deck_a.path, self.deck_b.path, self.biblioteca.count())
        if rutas != getattr(self, "_rutas_pintadas", None):
            self._rutas_pintadas = rutas
            self.biblioteca.pintar(self.deck_a.path, self.deck_b.path)
        try:
            self._auto_vigilar()
        except Exception:
            import traceback; traceback.print_exc()
        try:
            self._vigilar_sync()
        except Exception:
            import traceback; traceback.print_exc()
        try:
            self._tick_auto_enganche()
        except Exception:
            import traceback; traceback.print_exc()
        self.timeline.redraw()

    def closeEvent(self, event):
        try: CONSOLA.ocultar()
        except Exception: pass
        _cerrar_pool()
        self.biblioteca.guardar()
        self.mix_timer.stop()
        self.mix_pausa_timer.stop()
        self._smooth_timer.stop()
        self.magnet_timer.stop()
        self.mixer.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    w = AutoMix()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
