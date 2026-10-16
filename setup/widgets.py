"""AutoMix — widgets chicos reutilizables (logo, vúmetro, etiquetas)."""
import math
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget
from PySide6.QtCore import QPointF, QRectF, QSize, QTimer, Qt, Signal
from setup.ajustes import AJ, FUENTE_BOOST
from setup.tema import TEMA, _rgba


class LogoAutoMix(QWidget):
    """Logotipo con un visualizador de graves/medios/agudos que se mueve con el nivel real de la salida."""
    def __init__(self, fuente_nivel=None):
        super().__init__()
        self.fuente_nivel = fuente_nivel
        self.setMinimumHeight(58); self.setMaximumHeight(58)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._h = [0.1] * 9
        self._t = 0.0
        self._timer = QTimer(self); self._timer.timeout.connect(self._animar); self._timer.start(45)

    def _animar(self):
        try:
            nivel = float(self.fuente_nivel()) if self.fuente_nivel else 0.0
        except Exception:
            nivel = 0.0
        self._t += 0.045
        base = max(0.0, min(1.0, nivel * 3.2))
        for i in range(len(self._h)):
            ruido = 0.55 + 0.45 * math.sin(self._t * (5.0 + 1.7 * i) + i * 1.3) * math.sin(self._t * 2.3 + i)
            obj = 0.06 + base * (0.35 + 0.65 * abs(ruido))
            self._h[i] += (obj - self._h[i]) * (0.55 if obj > self._h[i] else 0.18)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # visualizador (si la columna es angosta, menos barras y más finitas)
        bw, gap = (6.0, 3.0) if w >= 190 else (4.0, 2.0)
        n = len(self._h) if w >= 150 else 5
        x0 = 4.0; base = h - 8.0; alto = h - 16.0
        for i in range(n):
            v = self._h[i]
            g = QLinearGradient(0, base - alto, 0, base)
            g.setColorAt(0.0, QColor(TEMA["magenta"])); g.setColorAt(1.0, QColor(TEMA["cian"]))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g))
            bh = max(3.0, alto * v)
            p.drawRoundedRect(QRectF(x0 + i * (bw + gap), base - bh, bw, bh), 2.0, 2.0)
        # texto: se achica hasta que entre
        xt = x0 + n * (bw + gap) + 8
        f = QFont(self.font()); f.setPointSizeF(max(18.0, 24.0 * AJ.escala * FUENTE_BOOST)); f.setBold(True); f.setItalic(True)
        fn = QFont(self.font()); fn.setPointSizeF(max(8.0, 10.0 * AJ.escala * FUENTE_BOOST)); fn.setBold(True)
        ancho_n = max(QFontMetricsF(fn).horizontalAdvance("Gustavo"), QFontMetricsF(fn).horizontalAdvance("Mayoraz"))
        con_nombre = (w - xt) >= 110 + ancho_n               # el nombre solo si la columna es lo bastante ancha
        libre = max(20.0, w - xt - 4 - ((ancho_n + 12) if con_nombre else 0))
        for _ in range(30):
            if QFontMetricsF(f).horizontalAdvance("AutoMix") <= libre or f.pointSizeF() <= 7.0:
                break
            f.setPointSizeF(f.pointSizeF() - 1.0)
        tam = f.pointSizeF()
        pa = QPainterPath(); pa.addText(xt, h * 0.60, f, "AutoMix")
        g2 = QLinearGradient(xt, 0, xt + QFontMetricsF(f).horizontalAdvance("AutoMix"), 0)
        g2.setColorAt(0.0, QColor("#ffffff")); g2.setColorAt(0.5, QColor(TEMA["cian"])); g2.setColorAt(1.0, QColor(TEMA["magenta"]))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g2)); p.drawPath(pa)
        if libre > 70:
            f2 = QFont(self.font()); f2.setPointSizeF(max(6.0, min(7.0 * AJ.escala * FUENTE_BOOST, tam * 0.36))); f2.setBold(True)
            f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
            p.setFont(f2); p.setPen(QColor(TEMA["suave"]))
            p.drawText(QPointF(xt + 3, h * 0.60 + max(9.0, tam * 0.7)), "DJ  MIXER")
        if con_nombre:                                        # "Gustavo / Mayoraz" a la derecha de AutoMix, en dos renglones
            xn = xt + QFontMetricsF(f).horizontalAdvance("AutoMix") + 12
            fm = QFontMetricsF(fn)
            y1 = h * 0.60 - fm.descent(); y2 = y1 + fm.height() * 0.95
            for txt, y in (("Gustavo", y1), ("Mayoraz", y2)):          # mismo degradé que AutoMix
                pn = QPainterPath(); pn.addText(xn, y, fn, txt)
                wt = fm.horizontalAdvance(txt)
                gn = QLinearGradient(xn, 0, xn + wt, 0)
                gn.setColorAt(0.0, QColor("#ffffff")); gn.setColorAt(0.5, QColor(TEMA["cian"])); gn.setColorAt(1.0, QColor(TEMA["magenta"]))
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(gn)); p.drawPath(pn)
        p.end()




class VuMeter(QWidget):
    """Medidor estéreo de la salida: LEDs verde → ámbar → rojo, pico retenido, y avisos de cuánto trabajan
    el compensador de nivel (COMP) y el limitador (LIM)."""
    DB_MIN = -48.0

    def __init__(self, fuente):
        super().__init__()
        self.fuente = fuente
        self.setMinimumHeight(40); self.setMaximumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._niv = [self.DB_MIN, self.DB_MIN]
        self._pico = [self.DB_MIN, self.DB_MIN]
        self._ret = [0.0, 0.0]
        self._gr_lim = 0.0; self._gr_comp = 0.0
        self._t = QTimer(self); self._t.timeout.connect(self._animar); self._t.start(33)

    @staticmethod
    def _db(x):
        return 20.0 * math.log10(max(1e-5, x))

    def _animar(self):
        try:
            pl, pr, glim, gcomp = self.fuente()
        except Exception:
            return
        for i, v in enumerate((self._db(pl), self._db(pr))):
            self._niv[i] = v if v > self._niv[i] else max(v, self._niv[i] - 1.1)       # sube al instante, baja con suavidad
            if v >= self._pico[i]:
                self._pico[i] = v; self._ret[i] = 28
            elif self._ret[i] > 0:
                self._ret[i] -= 1
            else:
                self._pico[i] = max(self.DB_MIN, self._pico[i] - 0.8)
        self._gr_lim = self._db(glim); self._gr_comp = self._db(gcomp)
        self.update()

    def _x(self, db, x0, ancho):
        return x0 + ancho * max(0.0, min(1.0, (db - self.DB_MIN) / (0.0 - self.DB_MIN)))

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        f = QFont(self.font()); f.setPointSizeF(max(7.0, 7.5 * AJ.escala * FUENTE_BOOST)); f.setBold(True); p.setFont(f)
        ancho_txt = max(60.0, min(110.0, w * 0.34))
        x0 = 16.0; ancho = max(30.0, w - ancho_txt - x0 - 6)
        alto_b = max(7.0, (h - 12) / 2.0 - 1)
        for i, nombre in enumerate(("L", "R")):
            y = 4 + i * (alto_b + 3)
            p.setPen(QColor(TEMA["suave"])); p.drawText(QRectF(0, y - 2, x0 - 3, alto_b + 4), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), nombre)
            p.setPen(QPen(QColor(TEMA["linea"]), 1)); p.setBrush(QBrush(QColor("#05070d")))
            p.drawRoundedRect(QRectF(x0, y, ancho, alto_b), 3, 3)
            xl = self._x(self._niv[i], x0, ancho)
            g = QLinearGradient(x0, 0, x0 + ancho, 0)
            g.setColorAt(0.0, QColor("#12d98a")); g.setColorAt(0.55, QColor("#22d3ff")); g.setColorAt(0.78, QColor("#ffb82e")); g.setColorAt(1.0, QColor("#ff3b4e"))
            if xl > x0 + 1:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g))
                p.drawRoundedRect(QRectF(x0 + 1, y + 1, xl - x0 - 1, alto_b - 2), 2, 2)
            p.setPen(QPen(QColor(5, 7, 13, 220), 1.4))                                   # separadores: efecto de LEDs
            k = x0 + 5.0
            while k < x0 + ancho:
                p.drawLine(QPointF(k, y + 1), QPointF(k, y + alto_b - 1)); k += 5.0
            xp = self._x(self._pico[i], x0, ancho)
            if self._pico[i] > self.DB_MIN + 1:
                p.setPen(QPen(QColor("#ffffff") if self._pico[i] < -1.0 else QColor(TEMA["rojo"]), 2)); p.drawLine(QPointF(xp, y), QPointF(xp, y + alto_b))
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))                                     # marcas -24 / -12 / -6 / 0
        for db in (-24, -12, -6):
            xx = self._x(db, x0, ancho); p.drawLine(QPointF(xx, h - 5), QPointF(xx, h - 2))
        # avisos
        xt = x0 + ancho + 8
        mitad = (h - 6) / 2.0
        comp = -self._gr_comp; lim = -self._gr_lim
        on_c = comp > 0.4; on_l = lim > 0.4
        p.setPen(QColor(TEMA["ambar"]) if on_c else QColor("#4a5473"))
        p.drawText(QRectF(xt, 2, ancho_txt, mitad), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), f"COMP  {-comp:+.1f}" if on_c else "COMP   0.0")
        p.setPen(QColor(TEMA["rojo"]) if on_l else QColor("#4a5473"))
        p.drawText(QRectF(xt, 2 + mitad, ancho_txt, mitad), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), f"LIM    {-lim:+.1f}" if on_l else "LIM     0.0")
        p.end()




class _OpcionApagada:
    """Reemplaza a una casilla que ya no existe en pantalla: siempre desactivada."""
    @staticmethod
    def isChecked():
        return False

    @staticmethod
    def setChecked(_v):
        pass




class EtiquetaAncha(QLabel):
    """Etiqueta de valor numérico con ancho CONSTANTE: mide el más ancho de los textos posibles, así al cambiar
    el valor ("-9.0 dB" ↔ "-12.5 dB") la grilla no se corre ni los deslizadores vecinos se redimensionan."""
    def __init__(self, textos, texto=""):
        super().__init__(texto)
        self._textos = list(dict.fromkeys(textos)) or [texto]
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    def sizeHint(self):
        fm = self.fontMetrics()
        w = max(fm.horizontalAdvance(t) for t in self._textos + [self.text()])
        h = super().sizeHint().height()
        return QSize(w + 2 * self.margin() + 4, h)

    def minimumSizeHint(self):
        return self.sizeHint()




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




class RelojReset(QWidget):
    """Reloj chiquito que aparece mientras el tempo vuelve al 100 %: el arco se llena y la aguja da la vuelta."""
    def __init__(self, parent, color):
        super().__init__(parent)
        self._color = QColor(color); self._k = 0.0
        self.setFixedSize(46, 46)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def set_progreso(self, k):
        self._k = max(0.0, min(1.0, k)); self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.4)); p.setBrush(QColor(TEMA["bg1"]))
        p.drawEllipse(r)
        for i in range(12):                                          # marcas de las horas
            a = math.radians(i * 30)
            c = r.center(); rr = r.width() / 2
            l = 2.6 if i % 3 == 0 else 1.4
            p.setPen(QPen(QColor(255, 255, 255, 150 if i % 3 == 0 else 70), 1.0))
            p.drawLine(QPointF(c.x() + math.sin(a) * (rr - l), c.y() - math.cos(a) * (rr - l)),
                       QPointF(c.x() + math.sin(a) * (rr - 0.6), c.y() - math.cos(a) * (rr - 0.6)))
        p.setPen(QPen(self._color, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(r.adjusted(1.6, 1.6, -1.6, -1.6), 90 * 16, int(-self._k * 360 * 16))     # progreso, en sentido horario
        a = self._k * 2 * math.pi; c = r.center()
        p.setPen(QPen(QColor("#ffffff"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(c, QPointF(c.x() + math.sin(a) * (r.width() / 2 - 4.5), c.y() - math.cos(a) * (r.width() / 2 - 4.5)))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(self._color); p.drawEllipse(c, 1.6, 1.6)




class EtiquetaTema(EtiquetaElidida):
    """Nombre del tema de un deck: al hacer clic avisa para ubicarlo en la lista de la biblioteca."""
    clicked = Signal()

    def __init__(self, texto=""):
        super().__init__(texto)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def _recortar(self):
        super()._recortar()
        base = self.toolTip()
        self.setToolTip((base + "\n" if base else "") + "Clic: ubicar este tema en la lista")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)




def qss_marco(selector, color, titulo=True):
    """Estilo de un cuadro (QGroupBox o QFrame) con el mismo degradé de color que los decks: el tono del cuadro es el de su acento."""
    c = QColor(color); h = max(0, c.hue())
    f1 = QColor.fromHsv(h, 185, 84).name(); f2 = QColor.fromHsv(h, 170, 40).name(); f3 = QColor.fromHsv(h, 150, 17).name()
    q = (f"{selector} {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {f1}, stop:0.55 {f2}, stop:1 {f3});"
         f" border:1px solid {_rgba(color, 120)}; border-radius:12px;" + (" margin-top:12px; padding-top:6px;" if titulo else "") + " }")
    if titulo:
        q += f" {selector}::title {{ subcontrol-origin:margin; subcontrol-position:top left; left:14px; padding:0 8px; color:{color}; font-weight:bold; }}"
    return q
