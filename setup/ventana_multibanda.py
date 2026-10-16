"""AutoMix — panel de multibanda y ecualizador inteligente (controles y ajustes)."""
import sys
from PySide6.QtWidgets import QCheckBox, QFrame, QGraphicsDropShadowEffect, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from setup.base import _log_diferido
from setup.config import guardar_config, leer_config
from setup.teclas import TeclaGlobalF2
from setup.tema import TEMA
from setup.widgets import EtiquetaAncha, EtiquetaElidida, VuMeter, qss_marco


class MultibandaMixin:
    """Panel de multibanda y ecualizador inteligente (controles y ajustes) (parte de la ventana principal)."""


    def _crear_panel_multibanda(self):
        cfg = leer_config()
        w = QGroupBox("🎛️ Multibanda Automática y Ecualizador Inteligente")
        w.setStyleSheet(qss_marco("QGroupBox", TEMA["violeta"]))
        g = QGridLayout(w)
        g.setContentsMargins(8, 6, 8, 4)
        g.setVerticalSpacing(3)
        g.setHorizontalSpacing(8)
        naranja = f"font-weight: bold; color: {TEMA['ambar']};"
        suave = f"color: {TEMA['suave']};"

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
        self.lbl_mb = EtiquetaAncha([f"{v} %" for v in range(0, 101)], f"{self.sld_mb.value()} %")
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
        rango_man = (0, 0, 80, 120, 120)        # en manual el Ratio llega a 8:1 y la Compensación a +12 dB: el ancho cubre el máximo
        self.mb_medidores = []
        for i, banda in enumerate(("Graves", "Medios", "Agudos")):
            col_banda = {"Graves": TEMA["magenta"], "Medios": TEMA["ambar"], "Agudos": TEMA["cian"]}[banda]
            cab = QLabel(banda); cab.setStyleSheet(f"font-weight: bold; color: {col_banda};"); cab.setMinimumWidth(48)
            g.addWidget(cab, 2 + i, 0)
            fila_m = []
            for j, (nombre, mn, mx, fmt, tip) in enumerate(columnas):
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(mn, mx); sl.setValue(mn); sl.setMinimumWidth(50)
                sl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                sl.setFocusPolicy(Qt.FocusPolicy.NoFocus); sl.setToolTip(tip)
                sl.setStyleSheet(f"QSlider::sub-page:horizontal {{ background: {col_banda}; border-radius:4px; }} QSlider::handle:horizontal {{ border-color: {col_banda}; }}")
                lbl = EtiquetaAncha([fmt(v) for v in range(mn, max(mx, rango_man[j]) + 1)], fmt(sl.value())); lbl.setStyleSheet(suave)
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
            lb = EtiquetaAncha([fmt(v) for v in range(mn, mx + 1)], fmt(sl.value()))
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
        self.btn_mix.setFixedHeight(38)
        self.btn_mix.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffd84a, stop:1 #ff9a00); color:#2a1700; font-weight:bold;"
            " border:1px solid #ffe08a; border-radius:11px; }"
            "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffe473, stop:1 #ffae2e); }"
            "QPushButton:pressed { background:#d98400; padding-top:2px; }"
            "QPushButton:disabled { background:#3a3322; color:#7a7155; border-color:#4a422c; }")
        _glow = QGraphicsDropShadowEffect(self.btn_mix); _glow.setBlurRadius(26); _glow.setOffset(0, 2); _glow.setColor(QColor(255, 160, 0, 130))
        self.btn_mix.setGraphicsEffect(_glow)
        # El botón Mezclar va abajo, a la derecha (debajo del Deck B), a la altura de la fila "Rejilla B"
        col_mix = QVBoxLayout(); col_mix.setContentsMargins(0, 0, 0, 0); col_mix.setSpacing(0)
        col_mix.addSpacing(30)                    # queda a la altura de la fila "Rejilla B"
        self.btn_mix.setMinimumWidth(230)
        col_mix.addWidget(self.btn_mix)
        self.chk_f2g = QCheckBox("⌨ F2 funciona con el programa en segundo plano")
        self.chk_f2g.setToolTip("Con esto activado, F2 mezcla aunque estés en otra ventana o programa (mientras AutoMix esté abierto).\n"
                                "Mientras esté activado, F2 no llega a los otros programas (por ejemplo, renombrar en el Explorador).")
        self.chk_f2g.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.f2_global = TeclaGlobalF2(self._mix_clicked)
        if sys.platform != "win32":
            self.chk_f2g.setVisible(False)
        self.chk_f2g.setChecked(bool(leer_config().get("f2_global", True)))
        self.chk_f2g.toggled.connect(self._f2_global_cambio)
        col_mix.addWidget(self.chk_f2g)
        self._f2_global_cambio(self.chk_f2g.isChecked(), guardar=False)
        col_mix.addStretch(1)
        self._fila_herr.addLayout(col_mix)
        self.spin_mix.setFixedWidth(58)           # corto: solo el número
        f_dur = self._fila_duracion               # la duración vive debajo de los dos decks (se arma acá porque el spin se crea antes)
        f_dur.addStretch(1)
        f_dur.addWidget(self.lbl_dur); f_dur.addWidget(self.spin_mix)
        f_dur.addSpacing(6)
        f_dur.addStretch(1)
        self._f_dur = f_dur                       # el botón de la consola se agrega acá al lado (antes del último estirador)
        f_vol = QHBoxLayout(); f_vol.addWidget(QLabel("🔊 Volumen")); f_vol.addWidget(self.sld_master, 1); f_vol.addWidget(self.lbl_master)
        self.crossfader.setToolTip("Crossfader A ↔ B (volumen + BPM compartido)")
        der.addLayout(self._cf_row)
        self.vu_meter = VuMeter(lambda: self.mixer.vu)
        der.addWidget(self.vu_meter)
        der.addStretch(1)
        der.addLayout(f_vol)                      # el volumen va debajo del fader, a la altura de la fila de Agudos
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
        _log_diferido("mb", "multibanda", f"intensidad {self.sld_mb.value()} % · máx {self.sld_lim.value()} dB · vel {self.sld_vel.value() / 10:.1f} dB/s · "
                      f"golpe {self.sld_golpe.value()} % · medios {self.sld_medios.value()} dB · agudos {self.sld_agudos.value()} dB")
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
        _log_diferido("vol", "volumen", f"general {v} %")
        self.lbl_master.setText(f"{v}%")
        self.mixer.set_volumen(v / 100.0)
        guardar_config(vol_general=int(v))
