"""AutoMix — auriculares: botones 🎧 por deck, elección del dispositivo y volumen."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout
from setup.base import log
from setup.config import guardar_config, leer_config
from setup.tema import COLOR_DECK_A, COLOR_DECK_B, TEMA
from setup.widgets import qss_marco


class _ComboRefresco(QComboBox):
    """Combo que vuelve a leer los dispositivos cada vez que se despliega (por si enchufaste el DAC después de abrir)."""
    def __init__(self, al_abrir):
        super().__init__()
        self._al_abrir = al_abrir

    def showPopup(self):
        try:
            self._al_abrir()
        except Exception:
            pass
        super().showPopup()


class AuricularesMixin:
    """Auriculares (PFL): escuchar un deck por otra salida de sonido (parte de la ventana principal)."""

    def _crear_auriculares(self):
        aur = self.mixer.aur
        cfg = leer_config()
        self.marco_aur = QFrame()                       # cuadro con degradé violeta, como los decks
        self.marco_aur.setObjectName("marcoAur")
        self.marco_aur.setStyleSheet(qss_marco("QFrame#marcoAur", TEMA["violeta"], titulo=False))
        col = QVBoxLayout(self.marco_aur); col.setContentsMargins(8, 4, 8, 4); col.setSpacing(3)
        fila1 = QHBoxLayout(); fila1.setContentsMargins(0, 0, 0, 0); fila1.setSpacing(4)
        fila1.addWidget(QLabel("<b>🎧 Auriculares</b>"))
        self.btn_cue = {}
        for deck, color in ((self.deck_a, COLOR_DECK_A), (self.deck_b, COLOR_DECK_B)):
            b = QPushButton(deck.name)
            b.setCheckable(True); b.setFixedSize(40, 26); b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(f"QPushButton {{ color:{color}; font-weight:bold; padding:0px; background:rgba(0,0,0,70);"
                            f" border:1px solid {color}; border-radius:7px; }}"
                            f"QPushButton:hover {{ background:rgba(255,255,255,30); }}"
                            f"QPushButton:checked {{ background:{color}; color:#0b1020; }}")
            b.setToolTip(f"Escuchar el Deck {deck.name} por los auriculares (antes del crossfader: se oye aunque a los parlantes no llegue).\n"
                         "Podés darle play y ajustar su tempo escuchándolo solo vos.")
            b.toggled.connect(lambda on, d=deck.name: self._cue_cambio(d, on))
            self.btn_cue[deck.name] = b
            fila1.addWidget(b)
        fila1.addStretch(1)
        col.addLayout(fila1)
        self.cmb_aur = _ComboRefresco(self._aur_refrescar)
        self.cmb_aur.setFixedHeight(26)
        self.cmb_aur.setMinimumContentsLength(14)
        self.cmb_aur.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_aur.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cmb_aur.setToolTip("Salida de sonido de los auriculares (por ejemplo tu DAC USB).")
        col.addWidget(self.cmb_aur)
        fila3 = QHBoxLayout(); fila3.setContentsMargins(0, 0, 0, 0); fila3.setSpacing(6)
        fila3.addWidget(QLabel("🔊"))
        self.sld_aur = QSlider(Qt.Orientation.Horizontal)
        self.sld_aur.setRange(0, 100); self.sld_aur.setFixedHeight(26)
        self.sld_aur.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sld_aur.setValue(int(cfg.get("aur_vol", 80)))
        aur.vol = self.sld_aur.value() / 100.0
        self.lbl_aur = QLabel(f"{self.sld_aur.value()} %")
        self.sld_aur.valueChanged.connect(self._aur_vol_cambio)
        fila3.addWidget(self.sld_aur, 1); fila3.addWidget(self.lbl_aur)
        col.addLayout(fila3)
        self._fila_herr.insertWidget(2, self.marco_aur, 0, Qt.AlignmentFlag.AlignTop)
        self._aur_nombre_pref = cfg.get("aur_nombre", "")
        self._aur_refrescar()
        self.cmb_aur.currentIndexChanged.connect(self._aur_dispositivo_cambio)
        self._aur_dispositivo_cambio()

    def _aur_refrescar(self):
        """Lee los dispositivos de salida y los pone en la lista, manteniendo la elección."""
        dev = self.mixer.aur.listar()
        actual = self.cmb_aur.currentData()
        bloq = self.cmb_aur.blockSignals(True)
        self.cmb_aur.clear()
        self.cmb_aur.addItem("— sin auriculares —", None)
        for idx, nombre in dev:
            self.cmb_aur.addItem(nombre, nombre)
        quiero = actual or getattr(self, "_aur_nombre_pref", "")
        i = self.cmb_aur.findData(quiero) if quiero else -1
        self.cmb_aur.setCurrentIndex(i if i >= 0 else 0)
        self.cmb_aur.blockSignals(bloq)

    def _aur_dispositivo_cambio(self, *_):
        aur = self.mixer.aur
        nombre = self.cmb_aur.currentData()
        if not nombre:
            aur.cerrar()
            for b in self.btn_cue.values():
                b.setChecked(False)
            guardar_config(aur_nombre="")
            return
        idx = next((i for i, n in aur.listar() if n == nombre), None)
        if idx is not None and aur.abrir(idx, nombre):
            self._aur_nombre_pref = nombre
            guardar_config(aur_nombre=nombre)
            log("audio", f"auriculares: {nombre}")
            self._set_status(f"🎧 Auriculares: {nombre}")
        else:
            motivo = aur.error or "no se encontró el dispositivo"
            log("audio", f"auriculares: no se pudo abrir «{nombre}» ({motivo})")
            self._set_status(f"⚠️ No se pudo abrir «{nombre}» para los auriculares")
            self.cmb_aur.blockSignals(True); self.cmb_aur.setCurrentIndex(0); self.cmb_aur.blockSignals(False)

    def _cue_cambio(self, nombre_deck, activo):
        aur = self.mixer.aur
        if activo and not aur.activo:
            QTimer.singleShot(0, lambda: self._cue_revertir(nombre_deck))
            self._set_status("🎧 Elegí primero la salida de los auriculares (en la lista de abajo)")
            return
        if nombre_deck == "A":
            aur.cue_a = bool(activo)
        else:
            aur.cue_b = bool(activo)

    def _cue_revertir(self, nombre_deck):
        b = self.btn_cue[nombre_deck]
        b.blockSignals(True); b.setChecked(False); b.blockSignals(False)

    def _aur_vol_cambio(self, v):
        self.mixer.aur.vol = v / 100.0
        self.lbl_aur.setText(f"{v} %")
        guardar_config(aur_vol=int(v))
