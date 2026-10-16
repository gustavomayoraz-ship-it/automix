"""AutoMix — dependencias, consola oculta y registro (log)."""
from pathlib import Path
import os
import sys
import threading
import time


# =====================================================================
# 1) DEPENDENCIAS DESDE ./dependencias_offline/<versión de Python>
# =====================================================================
ROOT = Path(__file__).resolve().parent.parent


VERSION_PY = f"{sys.version_info.major}.{sys.version_info.minor}"          # 3.12, 3.15…


# Las librerías compiladas sirven para UNA versión de Python: cada una tiene su carpeta (dependencias_offline/3.15, /3.14…)
# y el programa usa la de la versión con la que se abrió. Así se pueden tener varios Python instalados sin que se pisen.
OFFLINE = ROOT / "dependencias_offline" / VERSION_PY


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
    if all(_modulo_en_offline(m) for m, _pq in DEPENDENCIAS):      # todo instalado: ni abrir la ventana (ahorra ~1 s)
        return
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
            tk.Label(cont, text="Se guardan en dependencias_offline\\" + VERSION_PY, font=("Segoe UI", 9),
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
                self._cerrar_visor()                  # la cerraron con la X
        else:
            o = self._orig.get(nombre)
            if o is not None and not self._propia:
                try: o.write(texto); o.flush()
                except Exception: pass

    # ---- abrir / cerrar ----
    # La consola se muestra en una ventana APARTE (un proceso visor que recibe el texto por una tubería): así la X de
    # esa ventana se puede usar libremente: solo cierra el visor y el programa sigue como si nada.
    _VISOR = (
        "import sys, os\n"
        "try:\n"
        "    import ctypes\n"
        "    ctypes.windll.kernel32.SetConsoleTitleW('AutoMix - consola (se puede cerrar con la X)')\n"
        "    ctypes.windll.kernel32.SetConsoleOutputCP(65001)\n"
        "except Exception:\n"
        "    pass\n"
        "while True:\n"
        "    d = os.read(0, 65536)\n"
        "    if not d:\n"
        "        break\n"
        "    sys.stdout.buffer.write(d); sys.stdout.buffer.flush()\n"
    )

    def _ejecutable_visor(self):
        exe = sys.executable or "python"
        base = os.path.basename(exe).lower()
        if base == "pythonw.exe":
            cand = os.path.join(os.path.dirname(exe), "python.exe")
            if os.path.exists(cand):
                return cand
        return exe

    def mostrar(self):
        if not self.es_windows or self.visible:
            return self.visible
        if self._modo == "terminal":
            return False
        try:
            import subprocess
            self._proc = subprocess.Popen([self._ejecutable_visor(), "-c", self._VISOR], stdin=subprocess.PIPE,
                                          creationflags=0x00000010)        # CREATE_NEW_CONSOLE
            self._destino = _TuberiaTexto(self._proc.stdin)
            self._destino.write("".join(self.buffer)); self._destino.flush()
            self.visible = True
        except Exception:
            self._proc = None; self._destino = None; self.visible = False
        return self.visible

    def sondear(self):
        """Devuelve si la consola sigue abierta (si el usuario la cerró con la X, la da por cerrada)."""
        if self.visible and getattr(self, "_proc", None) is not None and self._proc.poll() is not None:
            self._cerrar_visor()
        return self.visible

    def _cerrar_visor(self):
        try:
            if self._destino: self._destino.close()
        except Exception:
            pass
        self._destino = None
        p = getattr(self, "_proc", None)
        self._proc = None
        if p is not None:
            try:
                if p.poll() is None: p.terminate()
            except Exception:
                pass
        self.visible = False

    def ocultar(self):
        if not self.es_windows or not self.visible:
            return
        self._cerrar_visor()

    def alternar(self):
        if self.visible: self.ocultar()
        else: self.mostrar()
        return self.visible




class _TuberiaTexto:
    """Escribe texto (utf-8) en la tubería hacia la ventana visor de la consola."""
    def __init__(self, f):
        self._f = f
    def write(self, t):
        self._f.write(t.encode("utf-8", "replace"))
    def flush(self):
        self._f.flush()
    def close(self):
        self._f.close()




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




_LOG_DIF = {}




def _log_diferido(clave, cat, msg, ms=450):
    """Para sliders: registra solo el valor final, no cada paso intermedio."""
    try:
        t = _LOG_DIF.get(clave)
        if t is None:
            from PySide6.QtCore import QTimer      # recién acá: base.py se carga antes de que existan las dependencias
            t = QTimer(); t.setSingleShot(True); _LOG_DIF[clave] = [t, None]
            t.timeout.connect(lambda c=clave: log(*_LOG_DIF[c][1]))
            t = _LOG_DIF[clave]
        t[1] = (cat, msg); t[0].start(ms)
    except Exception:
        pass




def log(cat, msg=""):
    """Todo lo que hace el programa va a la consola con hora: log('deck A', 'play')."""
    try:
        print(f"[{cat}] {msg}" if msg else f"[{cat}]")
    except Exception:
        pass


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
