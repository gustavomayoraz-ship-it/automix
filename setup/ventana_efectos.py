"""AutoMix — efectos de sonido: lista de efectos, botón que lo reproduce y volumen."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QPushButton, QSlider
from setup.config import guardar_config, leer_config
from setup.efectos import EFECTOS
from setup.tema import TEMA
from setup.widgets import qss_marco


class EfectosMixin:
    """Efectos de sonido para mezclar (parte de la ventana principal)."""

    def _crear_efectos(self):
        cfg = leer_config()
        fx = self.mixer.fx
        self.marco_fx = QFrame()                        # cuadro con degradé rojo
        self.marco_fx.setObjectName("marcoFx")
        self.marco_fx.setStyleSheet(qss_marco("QFrame#marcoFx", TEMA["rojo"], titulo=False).replace("border-radius:12px", "border-radius:9px"))
        fila = QHBoxLayout(self.marco_fx); fila.setContentsMargins(6, 3, 6, 3); fila.setSpacing(4)
        self.cmb_fx = QComboBox()
        self.cmb_fx.setFixedHeight(26); self.cmb_fx.setMinimumContentsLength(11)
        self.cmb_fx.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_fx.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for i, (nombre, _f, tip) in enumerate(EFECTOS):
            self.cmb_fx.addItem(nombre, i)
            self.cmb_fx.setItemData(i, tip, Qt.ItemDataRole.ToolTipRole)
        sel = int(cfg.get("fx_sel", 0))
        self.cmb_fx.setCurrentIndex(sel if 0 <= sel < len(EFECTOS) else 0)
        self.cmb_fx.setToolTip("Elegí el efecto de sonido; el botón ▶ lo reproduce.")
        self.cmb_fx.currentIndexChanged.connect(lambda i: guardar_config(fx_sel=int(i)))
        fila.addWidget(self.cmb_fx, 1)
        self.btn_fx = QPushButton("▶")
        self.btn_fx.setFixedSize(32, 26); self.btn_fx.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_fx.setStyleSheet("QPushButton { padding:0px; font-weight:bold; color:#2a0a10; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                                  " stop:0 #ff8a96, stop:1 #ff3b4e); border:1px solid #ffb3bb; border-radius:7px; }"
                                  "QPushButton:hover { background:#ff6272; } QPushButton:pressed { background:#d92a3b; }")
        self.btn_fx.setToolTip("Reproduce el efecto elegido (suena en la salida principal, mezclado con los temas).\n"
                               "Si lo tocás mientras suena, vuelve a empezar.")
        self.btn_fx.clicked.connect(self._fx_reproducir)
        fila.addWidget(self.btn_fx)
        self.sld_fx = QSlider(Qt.Orientation.Horizontal)
        self.sld_fx.setRange(0, 100); self.sld_fx.setFixedSize(54, 26); self.sld_fx.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sld_fx.setValue(int(cfg.get("fx_vol", 60)))
        fx.vol = self.sld_fx.value() / 100.0
        self.sld_fx.setToolTip("Volumen de los efectos (60 % queda por debajo de la música, sin ser invasivo).")
        self.sld_fx.valueChanged.connect(self._fx_vol_cambio)
        fila.addWidget(self.sld_fx)
        return self.marco_fx

    def _fx_reproducir(self):
        i = self.cmb_fx.currentIndex()
        self.mixer.fx.lanzar(i)
        self._set_status(f"{EFECTOS[i][0]}")

    def _fx_vol_cambio(self, v):
        self.mixer.fx.vol = v / 100.0
        guardar_config(fx_vol=int(v))
