"""AutoMix — línea de tiempo con los dos decks."""
import numpy as np
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPolygonItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView
from PySide6.QtCore import QPointF, Qt
from setup.ajustes import AJ, FUENTE_BOOST, fmt_time
from setup.tema import TEMA


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
        self.setStyleSheet(f"border:1px solid {TEMA['linea']}; border-radius:10px;")
        _fondo = QLinearGradient(0, 0, 0, 1); _fondo.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        _fondo.setColorAt(0.0, QColor("#05060b")); _fondo.setColorAt(0.5, QColor("#0a0f1b")); _fondo.setColorAt(1.0, QColor("#05060b"))
        self.setBackgroundBrush(QBrush(_fondo))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(150)

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
            ln.setPen(QPen(QColor(40, 52, 82, 130), 1))
            self.scene_.addItem(ln)
            txt = QGraphicsSimpleTextItem(fmt_time(t))
            txt.setBrush(QBrush(QColor(110, 128, 170)))
            f = QFont(); f.setPointSizeF(max(9.0, 8 * AJ.escala * FUENTE_BOOST)); txt.setFont(f)
            txt.setPos(x + 2, 2)
            self.scene_.addItem(txt)
            t += step_s

        cl = QGraphicsLineItem(0, mid, W, mid)
        cl.setPen(QPen(QColor(90, 110, 160, 140), 1))
        self.scene_.addItem(cl)

        if self.deck_a.analysis:
            self._draw_deck(self.deck_a.analysis, W, 0, mid - 1, anchor_a,
                            fill=QColor(34, 211, 255, 235),
                            beat_c=QColor(120, 230, 255, 70),
                            kick_c=QColor(255, 255, 255, 150),
                            downbeat_c=QColor(44, 255, 154, 200), core=QColor(10, 92, 140, 215))

        if self.deck_b.analysis:
            self._draw_deck(self.deck_b.analysis, W, mid + 1, H, anchor_b,
                            fill=QColor(255, 61, 154, 235),
                            beat_c=QColor(255, 150, 210, 70),
                            kick_c=QColor(255, 255, 255, 150),
                            downbeat_c=QColor(255, 184, 46, 210), core=QColor(130, 24, 90, 215))

        center_x = W / 2.0
        for ancho_ph, alfa_ph in ((10, 28), (5, 70)):                       # resplandor del playhead
            gl = QGraphicsLineItem(center_x, 0, center_x, H)
            gl.setPen(QPen(QColor(255, 240, 170, alfa_ph), ancho_ph)); self.scene_.addItem(gl)
        ph = QGraphicsLineItem(center_x, 0, center_x, H)
        ph.setPen(QPen(QColor(255, 250, 220), 2))
        self.scene_.addItem(ph)

        if self.manito_active:
            self.viewport().setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            self.viewport().setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def _draw_deck(self, analysis, W, top, bottom, anchor,
                   fill, beat_c, kick_c, downbeat_c, core=None):
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
            if core is not None:                                           # picos brillantes, centro más profundo
                gr = QLinearGradient(0, top, 0, bottom)
                gr.setColorAt(0.0, fill); gr.setColorAt(0.5, core); gr.setColorAt(1.0, fill)
                item.setBrush(QBrush(gr))
            else:
                item.setBrush(QBrush(fill))
            item.setPen(QPen(fill.lighter(125), 0.6))
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
            ln.setPen(QPen(downbeat_c, 2))
            self.scene_.addItem(ln)

        for k in analysis.get("kicks", []):
            x = self.t_to_x(k, W, anchor)
            if x < -2 or x > W + 2: continue
            ln = QGraphicsLineItem(x, top, x, bottom)
            ln.setPen(QPen(kick_c, 1.4))
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
