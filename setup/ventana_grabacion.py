"""AutoMix — grabación de la mezcla."""
from pathlib import Path
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from setup.base import ROOT, log


class GrabacionMixin:
    """Grabación de la mezcla (parte de la ventana principal)."""


    CARPETA_GRAB = ROOT / "grabaciones"

    def _alternar_grabacion(self):
        g = self.mixer.grabador
        if not g.activo:
            try:
                ruta = g.iniciar(self.CARPETA_GRAB)
            except Exception as e:
                log("grabación", f"no se pudo iniciar ({e})")
                self._set_status(f"⚠️ No se pudo grabar: {e}")
                return
            log("grabación", f"grabando en {ruta}")
            self.btn_grabar.setStyleSheet("QPushButton { background:#7a1620; border:2px solid #ff4d5e; color:#ffffff; font-weight:bold; }")
            self._tic_grabacion()
            self._t_grab.start()
        else:
            self._parar_grabacion()

    def _parar_grabacion(self):
        g = self.mixer.grabador
        self._t_grab.stop()
        ruta, seg = g.detener()
        self.btn_grabar.setStyleSheet("")
        self.btn_grabar.setText("⏺ Grabar mezcla")
        if ruta and seg > 0:
            m, s = divmod(int(seg), 60)
            self.lbl_grab.setText(f"✅ {Path(ruta).name} ({m}:{s:02d})")
            log("grabación", f"guardada {ruta} ({seg:.1f} s)" + (f" · {g.perdidos} muestras perdidas" if g.perdidos else ""))
            self._set_status(f"✅ Mezcla guardada en grabaciones/{Path(ruta).name}")
        else:
            self.lbl_grab.setText("")

    def _tic_grabacion(self):
        g = self.mixer.grabador
        if g._error:
            self._parar_grabacion()
            self.lbl_grab.setText("⚠️ Error de disco")
            return
        seg = int(g.segundos)
        h, r = divmod(seg, 3600); m, s = divmod(r, 60)
        t = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        self.btn_grabar.setText(("⏹ " if seg % 2 == 0 else "⏺ ") + f"Grabando  {t}")
        self.lbl_grab.setText("")

    def _abrir_carpeta_grabaciones(self):
        try:
            self.CARPETA_GRAB.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.CARPETA_GRAB)))
        except Exception as e:
            log("grabación", f"no se pudo abrir la carpeta ({e})")
