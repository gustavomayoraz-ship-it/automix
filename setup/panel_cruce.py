"""AutoMix — gráfico y panel de la forma de cruce."""
import math
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget
from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from setup.ajustes import AJ, FUENTE_BOOST
from setup.config import DEF_PUNTO_A, DEF_PUNTO_B, DEF_PUNTO_S, perfil_cruce_ab, perfil_cruce_bandas
from setup.tema import COLOR_DECK_A, COLOR_DECK_B, TEMA
from setup.widgets import qss_marco


class GraficoCruce(QWidget):
    def __init__(self):
        super().__init__()
        self.punto_a = DEF_PUNTO_A; self.punto_b = DEF_PUNTO_B; self.avance = None
        self.punto_s = DEF_PUNTO_S; self.bandas = False; self.simple = False
        self.setMinimumHeight(62)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def actualizar(self, pa, pb, avance=None, ps=None, bandas=False, fa=None, simple=False):
        self.simple = bool(simple)
        self.punto_a, self.punto_b, self.avance = pa, pb, avance
        self.fin_a = fa
        if ps is not None:
            self.punto_s = ps
        self.bandas = bool(bandas)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, m = self.width(), self.height(), 6
        fondo = QLinearGradient(0, 0, 0, h); fondo.setColorAt(0.0, QColor("#0a0e18")); fondo.setColorAt(1.0, QColor("#05070d"))
        p.setPen(QPen(QColor(TEMA["linea"]), 1)); p.setBrush(QBrush(fondo))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)
        x0, x1, yt, yb = m + 4.0, w - m - 4.0, m + 4.0, h - m - 4.0
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))                       # cuadrícula
        for f in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(x0 + (x1 - x0) * f, yt), QPointF(x0 + (x1 - x0) * f, yb))
            p.drawLine(QPointF(x0, yt + (yb - yt) * f), QPointF(x1, yt + (yb - yt) * f))
        pa, pb, la, lb = [], [], [], []
        for i in range(61):
            t = i / 60
            if self.simple:
                vs, ve = math.cos(t * math.pi / 2.0), math.sin(t * math.pi / 2.0); ls, le = vs, ve
            elif self.bandas:
                vs, ve, ls, le = perfil_cruce_bandas(t, self.punto_a, self.punto_b, self.punto_s, fin_a=getattr(self, "fin_a", None))
            else:
                vs, ve = perfil_cruce_ab(t, self.punto_a, self.punto_b); ls, le = vs, ve
            x = x0 + (x1 - x0) * t
            pa.append(QPointF(x, yb - vs * (yb - yt))); pb.append(QPointF(x, yb - ve * (yb - yt)))
            la.append(QPointF(x, yb - ls * (yb - yt) + 3)); lb.append(QPointF(x, yb - le * (yb - yt) + 3))
        ca, cb = QColor(COLOR_DECK_A), QColor(COLOR_DECK_B)

        def curva(pts, c, relleno=True):
            if relleno:                                                     # área translucida debajo de la curva
                poli = QPolygonF(pts + [QPointF(x1, yb), QPointF(x0, yb)])
                g = QLinearGradient(0, yt, 0, yb); g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 70)); g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g)); p.drawPolygon(poli)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 55), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)); p.drawPolyline(QPolygonF(pts))   # resplandor
            p.setPen(QPen(c, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)); p.drawPolyline(QPolygonF(pts))
        if self.bandas and not self.simple:              # graves: línea punteada, el traspaso se ve como un escalón
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ca.lighter(150), 2, Qt.PenStyle.DotLine)); p.drawPolyline(QPolygonF(la))
            p.setPen(QPen(cb.lighter(150), 2, Qt.PenStyle.DotLine)); p.drawPolyline(QPolygonF(lb))
            xs = x0 + (x1 - x0) * max(0.0, min(1.0, self.punto_s))          # dónde se traspasa el bajo
            p.setPen(QPen(QColor(TEMA["verde"]), 1, Qt.PenStyle.DashLine)); p.drawLine(QPointF(xs, yt), QPointF(xs, yb))
        curva(pa, ca); curva(pb, cb)
        if self.simple:
            fs = QFont(self.font()); fs.setPointSizeF(max(7.0, 7.5 * AJ.escala * FUENTE_BOOST)); fs.setBold(True); p.setFont(fs)
            p.setPen(QColor(TEMA["ambar"])); p.drawText(QRectF(x0, yt - 2, x1 - x0, 16), int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter), "CRUCE SIMPLE · BPM distintos")
        if self.avance is not None:
            xa = x0 + (x1 - x0) * max(0.0, min(1.0, self.avance))
            p.setPen(QPen(QColor(255, 255, 255, 60), 6)); p.drawLine(QPointF(xa, yt), QPointF(xa, yb))
            p.setPen(QPen(QColor("#ffffff"), 1.5)); p.drawLine(QPointF(xa, yt), QPointF(xa, yb))
        p.end()




class PanelCruce(QFrame):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        self.setObjectName("panelcruce")
        self.setStyleSheet(qss_marco("QFrame#panelcruce", "#3b82f6", titulo=False))
        self.setMinimumWidth(230); self.setMaximumWidth(300)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(3)
        self.chk = QCheckBox("🎚 Forma de cruce A/B")
        self.chk.setToolTip("Sin tilde: cruce clásico por volumen.")
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
        self.sl_a, self.lv_a = fila("A (sale):", COLOR_DECK_A, ventana.punto_a, "Momento en que el tema que sale comienza a bajar.")
        self.sl_b, self.lv_b = fila("B (entra):", COLOR_DECK_B, ventana.punto_b, "Momento en que el tema que entra comienza a subir (por bandas: entra a nivel pleno, con una subida corta).")
        self.chk_bandas = QCheckBox("🎛 Por bandas")
        self.chk_bandas.setToolTip("Medios y agudos se cruzan con las curvas de arriba; el BAJO (bombo y bajo, <150 Hz) es de uno solo a la vez\ny se traspasa en la línea del compás, sin cortes ni empaste. Sin tilde: el cruce clásico por volumen.")
        self.chk_bandas.setChecked(ventana.cruce_bandas)
        lay.addWidget(self.chk_bandas)
        self.chk_recetas = QCheckBox("🧠 Recetas automáticas")
        self.chk_recetas.setToolTip("Antes de cada mezcla mira dónde hay voz/melodía en los dos temas y elige la receta:\n· Voz nueva sobre la base vieja\n· Base nueva, voz vieja\n· Entrada instrumental bajo la voz vieja\n· Traspaso instrumental\nSi no hay datos, usa los deslizadores de abajo. (Necesita 'Por bandas'.)")
        self.chk_recetas.setChecked(ventana.recetas)
        self.chk_recetas.toggled.connect(ventana.set_recetas)
        lay.addWidget(self.chk_recetas)
        self.chk_comp = QCheckBox("⚖ Compensar nivel")
        self.chk_comp.setToolTip("Cuando suenan los dos temas a la vez, la suma suena más fuerte que cada uno.\nEsto baja un poco el total (hasta -5 dB, suave y automático) para que el volumen se mantenga parejo en la mezcla.")
        self.chk_comp.setChecked(ventana.comp_nivel)
        self.chk_comp.toggled.connect(ventana.set_comp)
        lay.addWidget(self.chk_comp)
        self.sl_s, self.lv_s = fila("Bajo (cambia):", TEMA["verde"], ventana.punto_s, "Momento de la mezcla en que el bajo pasa del tema que sale al que entra (en la línea de compás más próxima). 0 % = el nuevo trae su bajo desde el principio · 95 % = el viejo mantiene el bajo casi hasta el final.")
        self.lbl_dur = QLabel(); self.lbl_dur.hide()
        b_def = QPushButton("Valores por defecto"); b_def.clicked.connect(self._defecto)
        lay.addWidget(b_def)
        lay.addStretch()

        self.sl_a.valueChanged.connect(self._cambio); self.sl_b.valueChanged.connect(self._cambio)
        self.sl_s.valueChanged.connect(self._cambio); self.chk_bandas.toggled.connect(self._cambio)
        self.chk.toggled.connect(self._cambio)
        self._timer = QTimer(self); self._timer.timeout.connect(self._refrescar); self._timer.start(50)
        self.lv_a.setText(f"{self.sl_a.value()}%"); self.lv_b.setText(f"{self.sl_b.value()}%"); self.lv_s.setText(f"{self.sl_s.value()}%")

    def _defecto(self):
        self.sl_a.setValue(int(round(DEF_PUNTO_A * 100))); self.sl_b.setValue(int(round(DEF_PUNTO_B * 100))); self.sl_s.setValue(int(round(DEF_PUNTO_S * 100)))
        self.chk.setChecked(True)               # forma de cruce A/B activada
        self.chk_bandas.setChecked(True)        # por bandas
        self.chk_recetas.setChecked(False)      # recetas automáticas apagadas
        self.chk_comp.setChecked(True)          # compensar nivel
        try:                                    # multibanda, tono, volumen, zoom y marca del auto-enganche
            self.v.aplicar_valores_defecto()
        except Exception:
            import traceback; traceback.print_exc()

    def _cambio(self, *_):
        self.lv_a.setText(f"{self.sl_a.value()}%"); self.lv_b.setText(f"{self.sl_b.value()}%"); self.lv_s.setText(f"{self.sl_s.value()}%")
        self.sl_s.setEnabled(self.chk_bandas.isChecked())
        self.v.set_forma_cruce(self.sl_a.value() / 100.0, self.sl_b.value() / 100.0, self.chk.isChecked(),
                               self.sl_s.value() / 100.0, self.chk_bandas.isChecked())
        self._refrescar()

    def _refrescar(self):
        if not hasattr(self.v, "spin_mix"):
            return
        x = self.v.crossfader.value() / 100.0
        t = x if self.v._cf_dir == "AB" else 1.0 - x
        pl = self.v._plan_activo() if hasattr(self.v, "mix_timer") else None
        if self.v._cruce_simple():
            self.graf.actualizar(0.0, 0.0, t, None, False, 1.0, True)
        elif pl:                                           # durante una mezcla con receta, el gráfico muestra la receta
            self.graf.actualizar(pl["pa"], pl["pb"], t, pl["ps"], True, pl["fa"])
        else:
            self.graf.actualizar(self.sl_a.value() / 100.0, self.sl_b.value() / 100.0, t,
                                 self.sl_s.value() / 100.0, self.chk_bandas.isChecked() and self.chk.isChecked())
        self.lbl_dur.setText(f"⏱ Mezcla: {self.v.spin_mix.value()} s")
