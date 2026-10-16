"""AutoMix — tamaño de la ventana, escala de la interfaz y posición en pantalla."""
import re
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QGroupBox, QLayout, QScrollBar, QWidget
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QFont
from setup.ajustes import AJ, ESC_MIN, FUENTE_BOOST
from setup.base import log


class EscalaMixin:
    """Tamaño de la ventana, escala de la interfaz y posición en pantalla (parte de la ventana principal)."""


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

    def changeEvent(self, e):
        super().changeEvent(e)
        try:
            if e.type() == QEvent.Type.WindowStateChange:
                antes_max = bool(e.oldState() & Qt.WindowState.WindowMaximized)
                if antes_max and not (self.windowState() & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized | Qt.WindowState.WindowFullScreen)):
                    QTimer.singleShot(0, self._volver_al_minimo)      # al des-maximizar: vuelve al tamaño mínimo de arranque
        except Exception:
            pass

    def _volver_al_minimo(self):
        log("ventana", "restaurada: vuelve al tamaño mínimo")
        self._aplicar_escala(ESC_MIN)                  # el mínimo depende de la escala: primero la de arranque
        self._ir_al_minimo()

    def _ir_al_minimo(self):
        self.resize(self.minimumSizeHint())
        self._escalar_segun_ventana()
        self._ajustar_a_pantalla()

    def _a_la_esquina(self):
        """Botón ↖: la ventana vuelve al tamaño mínimo de arranque y queda pegada a la esquina superior izquierda.
        Se repite en varias pasadas hasta que el tamaño y la escala quedan firmes (Windows aplica el cambio de
        tamaño y el re-escalado de las letras con retraso: con una sola pasada había que apretar dos veces)."""
        log("ventana", "botón ↖: tamaño mínimo en la esquina superior izquierda")
        self._gen_esquina = getattr(self, "_gen_esquina", 0) + 1
        gen = self._gen_esquina
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()                          # el cambio de estado lo procesa Qt; después se acomoda
        def _pasada():
            if gen != self._gen_esquina:               # se apretó otra vez: manda la pasada nueva
                return
            self._aplicar_escala(ESC_MIN)
            QApplication.processEvents()
            self.layout().activate() if self.layout() is not None else None
            self.resize(self.minimumSizeHint())
            QApplication.processEvents()
            self._escalar_segun_ventana()
            self._ajustar_a_pantalla(esquina=True)
        for ms in (0, 120, 300, 600, 1000):
            QTimer.singleShot(ms, _pasada)

    def _ajustar_a_pantalla(self, esquina=False):
        """Al iniciar: que la ventana entre en la pantalla (barra de tareas incluida), centrada, con el
        contenido re-escalado y el timeline redibujado con su tamaño final. Con esquina=True queda arriba a la izquierda."""
        try:
            scr = self.screen() or QApplication.primaryScreen()
            ag = scr.availableGeometry()
            fg, g = self.frameGeometry(), self.geometry()
            marco_w, marco_h = fg.width() - g.width(), fg.height() - g.height()
            w = min(self.width(), ag.width() - marco_w)       # nunca más grande que la pantalla
            h = min(self.height(), ag.height() - marco_h)
            self.resize(w, h)
            if esquina:
                self.move(ag.left() + 4, ag.top() + 4)          # separada 4 px de los bordes
            else:
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
        s = max(ESC_MIN, min(1.6, int(s * 50) / 50.0))      # hacia abajo: nunca más grande que la ventana
        if abs(s - self._esc_actual) > 1e-9:
            self._aplicar_escala(s)
        tot = sum(self.split.sizes())
        if tot > 0:
            a = int(round(tot * self._ratio_lista))
            self.split.setSizes([a, tot - a])

    def _aplicar_escala(self, s):
        MAX = 16777215
        self._esc_actual = s; AJ.escala = s
        for wd, fb, pt, px in self._esc_fuentes:
            try:
                nf = QFont(fb)
                if pt > 0: nf.setPointSizeF(max(7.0, pt * s * FUENTE_BOOST))
                else: nf.setPixelSize(max(9, int(round(px * s * FUENTE_BOOST))))
                wd.setFont(nf)
            except RuntimeError:
                pass
        r = lambda v: int(round(v * s))
        for wd, minw, minh, maxw, maxh, ss in self._esc_widgets:
            try:
                wd.setMinimumSize(r(minw), r(minh))
                wd.setMaximumSize(maxw if maxw >= MAX else r(maxw), maxh if maxh >= MAX else r(maxh))
                if "font-size" in ss:
                    nuevo = re.sub(r"font-size:\s*(\d+(?:\.\d+)?)px", lambda m: f"font-size:{max(9, int(round(float(m.group(1)) * s * FUENTE_BOOST)))}px", ss)
                    if nuevo != wd.styleSheet(): wd.setStyleSheet(nuevo)
            except RuntimeError:
                pass
        for lay, l, t, ri, b, sp in self._esc_layouts:
            try:
                lay.setContentsMargins(r(l), r(t), r(ri), r(b))
                if sp >= 0: lay.setSpacing(r(sp))
            except RuntimeError:
                pass
        for gb in self.findChildren(QGroupBox):          # los títulos de grupo se cortaban: recalcular su ancho con la letra nueva
            gb.setTitle(gb.title()); gb.updateGeometry(); gb.update()
