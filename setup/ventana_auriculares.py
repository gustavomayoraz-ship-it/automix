"""AutoMix — auriculares: botones 🎧 por deck, elección del dispositivo y volumen."""
import time
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
        self.btn_cue = {}                              # (los botones A/B de escucha en vivo se sacaron: se usa el play de abajo)
        fila1.addStretch(1)
        self.btn_aur_ref = QPushButton("🔄")
        self.btn_aur_ref.setFixedSize(30, 26); self.btn_aur_ref.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_aur_ref.setStyleSheet("QPushButton { padding:0px; background:rgba(0,0,0,70); border:1px solid #888; border-radius:7px; }"
                                       "QPushButton:hover { background:rgba(255,255,255,30); }")
        self.btn_aur_ref.setToolTip("Buscar de nuevo los dispositivos de audio (para auriculares Bluetooth o un DAC conectado después de abrir el programa).\n"
                                    "Corta el sonido un instante.")
        self.btn_aur_ref.clicked.connect(self._aur_buscar_de_nuevo)
        fila1.addWidget(self.btn_aur_ref)
        col.addLayout(fila1)
        # Play propio de los auriculares: suena SOLO por ahí, con su propia posición (el deck no arranca, no se dispara
        # la mezcla automática y no se oye en los parlantes). La barra mueve la posición de la última previa tocada.
        aur.decks = {"A": self.deck_a, "B": self.deck_b}
        fila_p = QHBoxLayout(); fila_p.setContentsMargins(0, 0, 0, 0); fila_p.setSpacing(4)
        self.btn_prev = {}
        for deck, color in ((self.deck_a, COLOR_DECK_A), (self.deck_b, COLOR_DECK_B)):
            b = QPushButton(f"▶{deck.name}")
            b.setCheckable(True); b.setFixedSize(40, 26); b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(f"QPushButton {{ color:{color}; font-weight:bold; padding:0px; background:rgba(0,0,0,70);"
                            f" border:1px solid {color}; border-radius:7px; }}"
                            f"QPushButton:hover {{ background:rgba(255,255,255,30); }}"
                            f"QPushButton:checked {{ background:{color}; color:#0b1020; }}")
            b.setToolTip(f"Reproducir el tema cargado en el Deck {deck.name} SOLO en los auriculares.\n"
                         "No arranca el deck ni dispara la mezcla automática: tiene su propia posición.")
            b.toggled.connect(lambda on, d=deck.name: self._prev_cambio(d, on))
            self.btn_prev[deck.name] = b
            fila_p.addWidget(b)
        self.sld_prev = QSlider(Qt.Orientation.Horizontal)
        self.sld_prev.setRange(0, 1000); self.sld_prev.setFixedHeight(26)
        self.sld_prev.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sld_prev.setToolTip("Posición de la previa de auriculares (arrastrá para saltar a otra parte del tema).")
        self.sld_prev.sliderMoved.connect(self._prev_mover)
        self._prev_act = "A"
        fila_p.addWidget(self.sld_prev, 1)
        col.addLayout(fila_p)
        self._prev_timer = QTimer(self); self._prev_timer.setInterval(120)
        self._prev_timer.timeout.connect(self._prev_tick)
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
        # Arranque rápido: NO se consulta la lista de dispositivos ni se abre la salida ahora (en Windows puede tardar
        # varios segundos). Se muestra el nombre guardado y se abre recién al tocar A/B o al desplegar la lista.
        self.cmb_aur.addItem("— sin auriculares —", None)
        if self._aur_nombre_pref:
            self.cmb_aur.addItem(self._aur_nombre_pref, self._aur_nombre_pref)
            self.cmb_aur.setCurrentIndex(1)
        self.cmb_aur.currentIndexChanged.connect(self._aur_dispositivo_cambio)

    def _aur_refrescar(self):
        """Lee los dispositivos de salida y los pone en la lista, manteniendo la elección."""
        dev = self.mixer.aur.listar()
        actual = self.cmb_aur.currentData()
        bloq = self.cmb_aur.blockSignals(True)
        self.cmb_aur.clear()
        self.cmb_aur.addItem("— sin auriculares —", None)
        for idx, nombre, ch, api in dev:
            self.cmb_aur.addItem(nombre, nombre)
        quiero = actual or getattr(self, "_aur_nombre_pref", "")
        i = self.cmb_aur.findData(quiero) if quiero else -1
        self.cmb_aur.setCurrentIndex(i if i >= 0 else 0)
        self.cmb_aur.blockSignals(bloq)

    def _aur_buscar_de_nuevo(self):
        """Reinicia PortAudio para que aparezcan dispositivos conectados después de abrir (Bluetooth, USB)."""
        aur = self.mixer.aur
        pref = self.cmb_aur.currentData() or self._aur_nombre_pref
        self._set_status("🔄 Buscando dispositivos de audio…")
        for b in self.btn_cue.values():
            b.setChecked(False)
        self.mixer.reiniciar_audio()
        self._aur_refrescar()
        dev = aur.listar()
        for i, v, ch, api in dev:
            log("audio", f"salida {i}: {v} · {ch} canales · {api}")
        if pref:
            j = self.cmb_aur.findData(pref)
            if j >= 0:
                self.cmb_aur.setCurrentIndex(j)
        self._set_status(f"🔄 {len(dev)} salidas de audio encontradas — elegí tus auriculares en la lista")

    def _aur_dispositivo_cambio(self, *_):
        aur = self.mixer.aur
        nombre = self.cmb_aur.currentData()
        if not nombre:
            aur.cerrar()
            for b in self.btn_cue.values():
                b.setChecked(False)
            guardar_config(aur_nombre="")
            return
        self._aur_abrir(nombre)

    def _aur_abrir(self, nombre):
        """Abre la salida de auriculares con ese nombre. Devuelve True si quedó andando."""
        aur = self.mixer.aur
        if aur.activo and aur.nombre == nombre:
            return True
        t0 = time.perf_counter()
        d = next((x for x in aur.listar() if x[1] == nombre), None)
        if d is not None and aur.abrir(d[0], nombre, d[2], d[3]):
            self._aur_nombre_pref = nombre
            guardar_config(aur_nombre=nombre)
            log("audio", f"auriculares: {nombre} (abrió en {time.perf_counter() - t0:.2f} s)")
            self._set_status(f"🎧 Auriculares: {nombre}")
            return True
        motivo = aur.error or "no se encontró el dispositivo (¿está conectado? probá el botón 🔄)"
        log("audio", f"auriculares: no se pudo abrir «{nombre}» ({motivo})")
        self._set_status(f"⚠️ No se pudo abrir «{nombre}» para los auriculares")
        self.cmb_aur.blockSignals(True); self.cmb_aur.setCurrentIndex(0); self.cmb_aur.blockSignals(False)
        return False

    def _cue_cambio(self, nombre_deck, activo):
        aur = self.mixer.aur
        if activo and not aur.activo:
            nombre = self.cmb_aur.currentData()
            if not (nombre and self._aur_abrir(nombre)):          # la salida guardada se abre recién ahora (primer uso)
                QTimer.singleShot(0, lambda: self._cue_revertir(nombre_deck))
                if not nombre:
                    self._set_status("🎧 Elegí primero la salida de los auriculares (en la lista de abajo)")
                return
        if nombre_deck == "A":
            aur.cue_a = bool(activo)
        else:
            aur.cue_b = bool(activo)

    def _prev_cambio(self, nom, activo):
        aur = self.mixer.aur
        if activo:
            if not aur.activo:
                nombre = self.cmb_aur.currentData()
                if not (nombre and self._aur_abrir(nombre)):
                    QTimer.singleShot(0, lambda: self._prev_revertir(nom))
                    if not nombre:
                        self._set_status("🎧 Elegí primero la salida de los auriculares (en la lista de abajo)")
                    return
            if not aur.previa_play(nom):
                QTimer.singleShot(0, lambda: self._prev_revertir(nom))
                self._set_status(f"🎧 El Deck {nom} no tiene un tema cargado")
                return
            self._prev_act = nom
            self._prev_timer.start()
        else:
            aur.previa_pausa(nom)

    def _prev_revertir(self, nom):
        b = self.btn_prev[nom]
        b.blockSignals(True); b.setChecked(False); b.blockSignals(False)

    def _prev_mover(self, v):
        self.mixer.aur.previa_ir(self._prev_act, v / 1000.0)

    def _prev_tick(self):
        aur = self.mixer.aur
        hay = False
        for nom, b in self.btn_prev.items():
            sonando = aur.prev[nom].playing
            hay = hay or sonando
            if b.isChecked() != sonando:                   # terminó el tema o se cargó otro: el botón se suelta solo
                b.blockSignals(True); b.setChecked(sonando); b.blockSignals(False)
        if not self.sld_prev.isSliderDown():
            self.sld_prev.setValue(int(aur.previa_fraccion(self._prev_act) * 1000))
        if not hay:
            self._prev_timer.stop()

    def _cue_revertir(self, nombre_deck):
        b = self.btn_cue[nombre_deck]
        b.blockSignals(True); b.setChecked(False); b.blockSignals(False)

    def _aur_vol_cambio(self, v):
        self.mixer.aur.vol = v / 100.0
        self.lbl_aur.setText(f"{v} %")
        guardar_config(aur_vol=int(v))
