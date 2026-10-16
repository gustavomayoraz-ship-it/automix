"""AutoMix — ventana principal de AutoMix (la arman las partes ventana_*.py)."""
import sys
import time
import numpy as np
import sounddevice as sd
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import QTimer, Qt
from setup.ajustes import ESC_MIN, fmt_time
from setup.analisis import _cerrar_pool
from setup.barra import BarraProgresoConMarca
from setup.base import CONSOLA, log
from setup.biblioteca import Biblioteca
from setup.config import DEF_MARCA, DEF_PUNTO_A, DEF_PUNTO_B, DEF_PUNTO_S, guardar_config, leer_config
from setup.deck import Deck
from setup.mezclador import GlobalMixer
from setup.panel_cruce import PanelCruce
from setup.tema import COLOR_DECK_A, COLOR_DECK_B, TEMA, aplicar_tema
from setup.timeline import UnifiedTimeline
from setup.widgets import EtiquetaElidida, LogoAutoMix, _OpcionApagada, qss_marco
from setup.ventana_multibanda import MultibandaMixin
from setup.ventana_auto import AutomaticoMixin
from setup.ventana_auriculares import AuricularesMixin
from setup.ventana_biblioteca import BibliotecaMixin
from setup.ventana_escala import EscalaMixin
from setup.ventana_grabacion import GrabacionMixin
from setup.ventana_loop import LoopMixin
from setup.ventana_rejilla import RejillaMixin
from setup.ventana_sync import SyncMixin
from setup.ventana_mezcla import MezclaMixin


class AutoMix(MultibandaMixin, LoopMixin, AuricularesMixin, AutomaticoMixin, BibliotecaMixin, EscalaMixin, GrabacionMixin, RejillaMixin, SyncMixin, MezclaMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        try:
            aplicar_tema(QApplication.instance())
        except Exception:
            import traceback; traceback.print_exc()
        cfg = leer_config()
        self.punto_a = float(cfg.get("punto_a", DEF_PUNTO_A))
        self.punto_b = float(cfg.get("punto_b", DEF_PUNTO_B))
        self.cruce_ab = bool(cfg.get("cruce_ab", True))
        self.punto_s = float(cfg.get("punto_s", DEF_PUNTO_S))
        self.cruce_bandas = bool(cfg.get("cruce_bandas", True))
        self.recetas = bool(cfg.get("recetas", False))
        self.comp_nivel = bool(cfg.get("comp_nivel", True))
        self._plan = None                 # receta de la mezcla en curso: dict(pa, pb, ps, fa, nombre) o None
        self._cf_dir = "AB"
        self.carga_auto = True
        self.auto_s = int(cfg.get("auto_s", 30))
        self._fader_prev = None
        self._carga_pendiente = False
        self._mix_pausa_hecha = False
        self._marca_frac = float(cfg.get("marca_frac", DEF_MARCA))
        if self._marca_frac < 0:
            self._marca_frac = DEF_MARCA
        self._marca_disparada = False
        self._ultimo_prog_primario = 0.0
        self._ultimo_deck_primario = None
        self.setWindowTitle("AutoMix 🎚️")
        self.resize(1560, 850)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.split = split
        self.setCentralWidget(split)

        panel_lib = QWidget()
        lib_lay = QVBoxLayout(panel_lib)
        lib_lay.setContentsMargins(8, 8, 0, 8)
        lib_lay.setSpacing(4)
        self.logo = LogoAutoMix(lambda: getattr(getattr(self, "mixer", None), "nivel_vis", 0.0))
        lib_lay.addWidget(self.logo)
        self.lbl_lib = EtiquetaElidida("📁 Biblioteca — arrastrá carpetas acá")
        self.lbl_lib.setStyleSheet(f"color:{TEMA['suave']}; font-weight:bold;")
        lib_lay.addWidget(self.lbl_lib)
        self.ed_filtro = QLineEdit()
        self.ed_filtro.setPlaceholderText("Buscar…")
        self.ed_filtro.setClearButtonEnabled(True)
        lib_lay.addWidget(self.ed_filtro)
        self.biblioteca = Biblioteca()
        self.biblioteca.setStyleSheet(qss_marco("QListWidget", "#2bb5d6", titulo=False))     # el fondo de la lista, con el mismo degradé de color
        lib_lay.addWidget(self.biblioteca, stretch=1)
        lib_btns = QHBoxLayout()
        b_limpiar = QPushButton("Vaciar"); b_limpiar.clicked.connect(self.biblioteca.limpiar)
        self.btn_ordenar = QPushButton("🔃 Ordenar por BPM")
        self.btn_ordenar.clicked.connect(self._ordenar_biblioteca_bpm)
        self.btn_reanalizar = QPushButton("🔄 Re-analizar")
        self.btn_reanalizar.setToolTip("Vuelve a analizar el BPM de TODOS los temas de la lista (guía: el BPM del nombre del archivo)")
        self.btn_reanalizar.clicked.connect(self._reanalizar_biblioteca)
        lib_btns.addWidget(b_limpiar); lib_btns.addWidget(self.btn_ordenar)
        lib_btns.addWidget(self.btn_reanalizar)
        lib_lay.addLayout(lib_btns)
        # 🎼 Armónico y 🥁 En frase se quitaron de la pantalla: quedan siempre apagados
        # (el siguiente tema es el que sigue en la lista, ordenada por BPM, y la mezcla automática arranca al llegar a la marca).
        self.chk_armonico = _OpcionApagada()
        self.chk_frases = _OpcionApagada()
        self.chk_wsola = QCheckBox("🎚 Tono fijo (WSOLA)")
        self.chk_wsola.setToolTip("Al cambiar la velocidad de un tema (tempo, enganche, mezcla) el tono NO cambia: el audio se estira con WSOLA.\n"
                                  "Destildado: la velocidad cambia el tono, como en un disco de vinilo.")
        self.chk_wsola.setChecked(bool(leer_config().get("wsola", True)))
        Deck.WSOLA = self.chk_wsola.isChecked()
        self.chk_wsola.toggled.connect(self._wsola_cambio)
        lib_lay.addWidget(EtiquetaElidida("Arrastrá un tema a Deck A o B"))
        self.ed_filtro.textChanged.connect(self._filtrar_biblioteca)
        self.biblioteca.cambio.connect(self._biblioteca_cambio)
        self.biblioteca.aviso.connect(self._set_status)
        self.biblioteca.itemDoubleClicked.connect(self._biblioteca_doble_clic)
        split.addWidget(panel_lib)

        central = QWidget()
        split.addWidget(central)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1)
        split.setSizes([470, 1090])
        split.setChildrenCollapsible(False)
        panel_lib.setMinimumWidth(340)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        decks_row = QHBoxLayout()
        decks_row.setSpacing(14)
        self.deck_a = Deck("A", COLOR_DECK_A, self._on_analysis)
        self.deck_b = Deck("B", COLOR_DECK_B, self._on_analysis)
        self.deck_a.on_ubicar_cb = self.deck_b.on_ubicar_cb = self._ubicar_en_lista
        self.deck_a.on_play_cb = self._auto_sync
        self.deck_b.on_play_cb = self._auto_sync
        # Callback para que el botón reset avise a la ventana y se redibuje el timeline
        self.deck_a.on_reset_cb = self._on_reset_deck
        self.deck_b.on_reset_cb = self._on_reset_deck
        self.panel_cruce = PanelCruce(self)
        izq = QVBoxLayout(); izq.setSpacing(6); izq.setContentsMargins(0, 0, 0, 0)       # columna de los dos decks (+ la duración debajo)
        decks_ab = QHBoxLayout(); decks_ab.setSpacing(14); decks_ab.setContentsMargins(0, 0, 0, 0)
        decks_ab.addWidget(self.deck_a, stretch=1)
        decks_ab.addWidget(self.deck_b, stretch=1)
        izq.addLayout(decks_ab)
        izq.addStretch(1)                        # la duración queda centrada en el hueco entre los decks y el panel de abajo
        self._fila_duracion = QHBoxLayout(); self._fila_duracion.setContentsMargins(0, 0, 0, 0); self._fila_duracion.setSpacing(6)
        izq.addLayout(self._fila_duracion)       # a la altura del botón "Valores por defecto", justo debajo de los dos decks
        self._fila_herr = QHBoxLayout(); self._fila_herr.setContentsMargins(0, 0, 0, 0); self._fila_herr.setSpacing(18)
        izq.addLayout(self._fila_herr)           # herramientas: a la izquierda la rejilla (en vertical), a la derecha la grabación
        self.marco_rej = QFrame()                  # cuadro con degradé cian para las rejillas y el botón Auto
        self.marco_rej.setObjectName("marcoRej")
        self.marco_rej.setStyleSheet(qss_marco("QFrame#marcoRej", TEMA["cian"], titulo=False))
        self._fila_rej = QVBoxLayout(self.marco_rej); self._fila_rej.setContentsMargins(8, 4, 8, 4); self._fila_rej.setSpacing(3)
        self._fila_grab = QVBoxLayout(); self._fila_grab.setContentsMargins(0, 0, 0, 0); self._fila_grab.setSpacing(4)
        self._fila_herr.addWidget(self.marco_rej, 0, Qt.AlignmentFlag.AlignTop)
        self._fila_herr.addLayout(self._fila_grab)
        self._fila_herr.addStretch(1)
        izq.addStretch(1)
        decks_row.addLayout(izq, stretch=1)
        decks_row.addWidget(self.panel_cruce, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(decks_row)

        self.mixer = GlobalMixer(self.deck_a, self.deck_b, sr=44100, blocksize=1024)
        self.mixer.comp_activo = self.comp_nivel
        self.mixer.start()

        cf_row = QHBoxLayout()           # el crossfader va en el panel de la derecha de los deslizadores
        self._cf_row = cf_row
        cf_row.addWidget(QLabel("A"))
        self.crossfader = QSlider(Qt.Orientation.Horizontal)
        self.crossfader.setRange(0, 100)
        self.crossfader.setValue(0)
        self.crossfader.valueChanged.connect(self._update_cf)
        cf_row.addWidget(self.crossfader, stretch=1)
        cf_row.addWidget(QLabel("B"))
        self.sld_master = QSlider(Qt.Orientation.Horizontal)
        self.sld_master.setRange(0, 100)
        self.sld_master.setMinimumWidth(90)
        self.sld_master.setValue(int(leer_config().get("vol_general", 100)))
        self.lbl_master = QLabel(f"{self.sld_master.value()}%")
        self.lbl_master.setMinimumWidth(38)
        self.sld_master.valueChanged.connect(self._vol_general_cambio)
        self.mixer.set_volumen(self.sld_master.value() / 100.0)
        self.mixer._gain_act = self.mixer.gain_obj

        ctrl_box = QGroupBox("🎛️ Controles")
        ctrl_box.setFixedHeight(60)
        c = QHBoxLayout(ctrl_box)
        c.setContentsMargins(8, 4, 8, 4)

        self.btn_mix = QPushButton("🎬 Mezclar (F2)")
        self.btn_mix.setFixedHeight(30)
        self.btn_mix.clicked.connect(self._mix_clicked)
        self.shortcut_f2 = QShortcut(QKeySequence(Qt.Key.Key_F2), self)
        self.shortcut_f2.activated.connect(self._mix_clicked)

        self.shortcut_espacio = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.shortcut_espacio.setContext(Qt.ShortcutContext.WindowShortcut)
        self.shortcut_espacio.activated.connect(self._toggle_play_pausa)

        self.lbl_dur = QLabel("Duración")
        self.spin_mix = QSpinBox()
        self.spin_mix.setRange(1, 120)
        self.spin_mix.setSuffix(" s")
        self.spin_mix.setFixedHeight(30)
        self.spin_mix.setValue(self._cargar_duracion_mezcla())
        self.btn_mix.setText(f"🎬 Mezclar ({self.spin_mix.value()}s) [F2]")
        self.spin_mix.valueChanged.connect(self._duracion_mezcla_cambio)
        c.addStretch()

        contenedor_inferior = QWidget()
        ci_layout = QVBoxLayout(contenedor_inferior)
        ci_layout.setContentsMargins(0, 0, 0, 0)
        ci_layout.setSpacing(6)
        ci_layout.addWidget(self._crear_panel_multibanda())
        root.addWidget(contenedor_inferior)

        self.lbl_status = EtiquetaElidida("Listo con Auto-Gain activado. Espacio = pausa/play.")
        self.lbl_status.setStyleSheet(
            "color:#9fe; background:#111; padding:4px; "
            "border:1px solid #333; border-radius:4px; font-size:11px;"
        )
        self.lbl_status.setFixedHeight(24)
        fila_estado = QHBoxLayout()
        fila_estado.setContentsMargins(0, 0, 0, 0)
        fila_estado.setSpacing(4)
        self.lbl_status.setVisible(False)        # la barra negra de estado ya no se muestra (el texto sigue disponible por tooltip)
        fila_estado.addStretch(1)
        self.btn_consola = QPushButton("🖥")
        self.btn_consola.setCheckable(True)
        self.btn_consola.setFixedSize(76, 52)
        self.btn_consola.setStyleSheet("QPushButton { font-size:30px; padding:0px; }")
        self.btn_consola.setToolTip("Mostrar / ocultar la consola (todo lo que hace el programa, con hora)")
        self.btn_consola.clicked.connect(self._alternar_consola)
        self._t_consola = QTimer(self); self._t_consola.setInterval(600)       # si la cerraron con la X, el botón se suelta
        self._t_consola.timeout.connect(lambda: self.btn_consola.setChecked(CONSOLA.sondear()) if CONSOLA._modo != "terminal" else None)
        self._t_consola.start()
        if not CONSOLA.es_windows:
            self.btn_consola.setVisible(False)
        self._f_dur.insertWidget(self._f_dur.count() - 1, self.btn_consola)   # al costado de Duración, mismo tamaño
        self.btn_grabar = QPushButton("⏺ Grabar mezcla")
        self.btn_grabar.setFixedHeight(30)
        self.btn_grabar.setMinimumWidth(190)
        self.btn_grabar.setToolTip("Graba en un .wav todo lo que suena (la mezcla completa, con ecualizador y limitador)")
        self.btn_grabar.clicked.connect(self._alternar_grabacion)
        self.btn_carpeta_grab = QPushButton("📂")
        self.btn_carpeta_grab.setFixedSize(52, 30)
        self.btn_carpeta_grab.setToolTip("Abrir la carpeta con las mezclas grabadas")
        self.btn_carpeta_grab.clicked.connect(self._abrir_carpeta_grabaciones)
        self.lbl_grab = EtiquetaElidida("")
        self.lbl_grab.setFixedHeight(30); self.lbl_grab.setStyleSheet("color:#9fe3c6; font-size:12px;")
        fila_g = QHBoxLayout(); fila_g.setSpacing(6); fila_g.setContentsMargins(0, 0, 0, 0)
        fila_g.addWidget(self.btn_grabar); fila_g.addWidget(self.btn_carpeta_grab)
        self._fila_grab.addLayout(fila_g)
        self._fila_grab.addWidget(self.lbl_grab)                 # (el nombre del .wav guardado)
        self._fila_grab.addWidget(self.chk_wsola)                # misma línea que el botón Auto
        self.chk_wsola.setFixedHeight(30)
        self._fila_grab.addStretch(1)
        self._crear_auriculares()                                # columna 🎧 entre la grabación y el botón Mezclar
        self._t_grab = QTimer(self); self._t_grab.setInterval(250)
        self._t_grab.timeout.connect(self._tic_grabacion)
        for deck, col in ((self.deck_a, COLOR_DECK_A), (self.deck_b, COLOR_DECK_B)):
            fila_d = QHBoxLayout(); fila_d.setSpacing(4); fila_d.setContentsMargins(0, 0, 0, 0)
            fila_d.addWidget(QLabel(f"<b style='color:{col}'>Rejilla {deck.name}</b>"))
            for txt, tip, fn in (
                ("÷2", "BPM a la mitad (si el análisis detectó el doble)", lambda _=False, d=deck: self._rejilla(d, factor=0.5)),
                ("×2", "BPM al doble (si el análisis detectó la mitad)", lambda _=False, d=deck: self._rejilla(d, factor=2.0)),
                ("①", "Poner el \"1\" del compás en la posición actual (pausá el tema justo en el golpe fuerte con la manito)", lambda _=False, d=deck: self._rejilla(d, uno=True)),
            ):
                b = QPushButton(txt); b.setFixedSize(44, 28); b.setToolTip(tip)
                b.setStyleSheet("QPushButton { padding:0px; font-size:16px; font-weight:bold; }")
                b.clicked.connect(fn); b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                fila_d.addWidget(b)
            fila_d.addStretch(1)
            self._fila_rej.addLayout(fila_d)
        self.btn_auto_rej = QPushButton("🎯 Auto")
        self.btn_auto_rej.setCheckable(True)
        self.btn_auto_rej.setFixedHeight(28); self.btn_auto_rej.setMinimumWidth(130)
        self.btn_auto_rej.setToolTip("Auto-grilla (verde = activada, rojo = desactivada).\nActivada: revisa sin parar los temas que entran, "
                                     "corrige el BPM doble/mitad, centra la grilla en los bombos y los empareja (tempo + compases).")
        self.btn_auto_rej.setChecked(bool(leer_config().get("auto_grilla", False)))
        for _b in (self.btn_auto_rej, self.btn_grabar, self.btn_carpeta_grab):
            _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)         # que la barra espaciadora / Enter nunca los active por accidente
        self._estilo_auto_rej()
        self.btn_auto_rej.toggled.connect(self._auto_rej_cambio)
        self._rej_visto = {}
        self._t_auto_rej = QTimer(self); self._t_auto_rej.setInterval(800)
        self._t_auto_rej.timeout.connect(self._vigilar_rejilla)
        if self.btn_auto_rej.isChecked():
            self._t_auto_rej.start()
        fila_au = QHBoxLayout(); fila_au.setContentsMargins(0, 0, 0, 0)
        fila_au.addWidget(self.btn_auto_rej); fila_au.addStretch(1)
        self._fila_rej.addLayout(fila_au)
        self.lbl_rej = QLabel(""); self.lbl_rej.setWordWrap(True); self.lbl_rej.setStyleSheet("color:#9fe3c6; font-size:12px;")
        izq.addWidget(self.lbl_rej)               # lo que encontró y corrigió el botón Auto
        self.btn_esquina = QPushButton("↖")
        self.btn_esquina.setFixedSize(76, 52)
        self.btn_esquina.setStyleSheet("QPushButton { font-size:34px; padding:0px; }")
        self.btn_esquina.setToolTip("Ventana al tamaño mínimo, en la esquina superior izquierda de la pantalla")
        self.btn_esquina.clicked.connect(self._a_la_esquina)
        self._f_dur.insertSpacing(self._f_dur.count() - 1, 6)
        self._f_dur.insertWidget(self._f_dur.count() - 1, self.btn_esquina)   # al lado de la consola

        barra_box = QGroupBox("⚓ Auto-enganche — progreso del tema sonando")
        barra_box.setFixedHeight(84)
        barra_box.setStyleSheet(qss_marco("QGroupBox", TEMA["ambar"]))
        bl = QHBoxLayout(barra_box)
        bl.setContentsMargins(8, 6, 8, 4)
        bl.setSpacing(8)
        self.barra_prog = BarraProgresoConMarca()
        self.barra_prog.set_marca(self._marca_frac)
        self.barra_prog.marca_cambiada.connect(self._marca_cambiada)
        self.barra_prog.marca_cruzada.connect(self._marca_cruzada)
        bl.addWidget(self.barra_prog, stretch=1)
        self.lbl_marca = QLabel()
        self.lbl_marca.setMinimumWidth(190)
        self.lbl_marca.setStyleSheet(f"color:{TEMA['suave']}; font-size:11px;")
        self._actualizar_lbl_marca()
        bl.addWidget(self.lbl_marca)
        root.addWidget(barra_box)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Zoom (px/s):"))
        self.sld_zoom = QSlider(Qt.Orientation.Horizontal)
        self.sld_zoom.setRange(5, 300)
        self.sld_zoom.setValue(40)
        self.sld_zoom.valueChanged.connect(self._update_zoom)
        zoom_row.addWidget(self.sld_zoom, stretch=1)
        self.lbl_zoom = QLabel("40")
        self.lbl_zoom.setFixedWidth(50)
        zoom_row.addWidget(self.lbl_zoom)
        root.addLayout(zoom_row)

        tl_box = QGroupBox("🎼 Timeline — Playhead FIJO al centro")
        tl_box.setStyleSheet(qss_marco("QGroupBox", TEMA["verde"]))
        tl_lay = QVBoxLayout(tl_box)
        tl_lay.setContentsMargins(4, 4, 4, 4)
        self.timeline = UnifiedTimeline(self.deck_a, self.deck_b, on_manito_cb=self._on_manito_release)
        tl_lay.addWidget(self.timeline)
        root.addWidget(tl_box, stretch=1)

        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

        self.mix_timer = QTimer()
        self.mix_timer.timeout.connect(self._mix_step)
        self.mix_steps_total = 0
        self.mix_steps_done = 0
        self.mix_from = 0
        self.mix_to = 0

        self.mix_pausa_timer = QTimer(self)
        self.mix_pausa_timer.setSingleShot(True)
        self.mix_pausa_timer.timeout.connect(self._reanudar_mix)

        self._target_rate_a = None
        self._target_rate_b = None
        self._alpha_a = 0.05
        self._alpha_b = 0.05
        self._smooth_timer = QTimer()
        self._smooth_timer.timeout.connect(self._smooth_tempo)
        self._smooth_timer.start(20)

        self.magnet_on = False
        self._err_filtrado = 0.0
        self._sync_I = 0.0
        self._sync_t = None
        self._sync_n = 0
        self._sync_hist = []
        self.master_for_magnet = None
        self.slave_for_magnet = None
        self.magnet_timer = QTimer()
        self.magnet_timer.timeout.connect(self._magnet_correct)

        self.manito_on = True

        self.biblioteca.cargar()
        self._update_cf()
        QTimer.singleShot(0, self._restaurar_decks)

        self._esc_actual = 1.0
        self._ratio_lista = 470.0 / 1560.0
        self._esc_timer = QTimer(self)
        self._esc_timer.setSingleShot(True)
        self._esc_timer.timeout.connect(self._escalar_segun_ventana)
        self._registrar_escala()
        self.split.splitterMoved.connect(self._splitter_movido)

        # Tamaño "natural" (escala 1.0) = lo que mide el contenido de verdad. La escala sale de
        # comparar la ventana con ese tamaño, así el contenido SIEMPRE entra en la ventana
        # (antes se usaba un 1560x850 fijo y, al agregar paneles, el mínimo pasaba la pantalla).
        # El tamaño inicial es el MÍNIMO que soporta el formulario con las letras ya en su tamaño normal
        # (escala 1.0): ni más grande, ni con letras diminutas.
        self._aplicar_escala(ESC_MIN)
        mh = self.minimumSizeHint()
        self.ESC_BASE_W = mh.width() / ESC_MIN * 1.05    # +5 % de holgura: el mínimo no crece exacto con la escala
        self.ESC_BASE_H = mh.height() / ESC_MIN * 1.05
        self.resize(mh)
        QTimer.singleShot(0, self._ir_al_minimo)

        self.biblioteca.nuevos.connect(lambda: QTimer.singleShot(1500, self._auto_analizar))
        self._ordenar_lista()                                 # al abrir: lista ordenada (cadena armónica/frase o, si no, por BPM)
        self._ordenar_al_terminar = True                      # y otra vez cuando termine de analizar lo que falte
        QTimer.singleShot(2500, self._auto_analizar)

    def _wsola_cambio(self, v):
        Deck.WSOLA = bool(v)
        guardar_config(wsola=bool(v))
        log("audio", "tono fijo (WSOLA) " + ("activado" if v else "desactivado: la velocidad cambia el tono"))

    def _alternar_consola(self):
        visible = CONSOLA.alternar()
        self.btn_consola.setChecked(visible)
        if CONSOLA._modo == "terminal":
            self._set_status("🖥 Lo abriste desde una terminal: ahí mismo ves todo lo que hace")
            return
        self._set_status("🖥 Consola abierta (se cierra con este botón o con su X)" if visible else "🖥 Consola oculta")

    def _set_status(self, text):
        if text != getattr(self, "_ult_status_log", None):          # lo que el programa "dice" también va a la consola
            self._ult_status_log = text
            log("estado", text)
        self.lbl_status.setText(text)
        try:
            self.btn_consola.setToolTip(f"{text}\n\nMostrar / ocultar la consola (todo lo que hace el programa, con hora)")
        except Exception:
            pass

    def _on_reset_deck(self, deck):
        """Callback que dispara el Deck al hacer reset. Redibuja el timeline
        y muestra un mensaje de status para dar feedback visual."""
        try:
            self.timeline.redraw()
        except Exception:
            pass
        if deck is self.deck_a: self._target_rate_a = None
        else: self._target_rate_b = None
        self._set_status(f"⟲ Deck {deck.name}: tempo al 100 %")

    def _update_zoom(self):
        v = self.sld_zoom.value()
        self.lbl_zoom.setText(str(v))
        self.timeline.set_zoom_px(float(v))

    def _fin_ajuste(self, deck, completo):
        ep = self.__dict__.setdefault("_aj_ep", {})
        if ep.pop(id(deck), None) is not None:
            if completo:
                deck.mostrar_ajuste(1.0)
            deck.ocultar_ajuste()

    def _on_manito_release(self, deck):
        anchor = self.timeline.anchor_a if deck == "A" else self.timeline.anchor_b
        d = self.deck_a if deck == "A" else self.deck_b
        d.pos_manual = True                          # lo ubicó el usuario: si es el que entra, la mezcla arranca desde ahí
        self._set_status(f"✋ Deck {deck} movido a {fmt_time(anchor)}")

    def closeEvent(self, event):
        log("programa", "cerrando AutoMix")
        try: self.f2_global.quitar()
        except Exception: pass
        try:
            if self.mixer.grabador.activo:
                self._parar_grabacion()          # que el .wav quede completo
        except Exception:
            pass
        try:
            guardar_config(decks_cargados={"A": self.deck_a.path, "B": self.deck_b.path})     # al abrir vuelven a quedar cargados
        except Exception:
            pass
        try: CONSOLA.ocultar()
        except Exception: pass
        _cerrar_pool()
        self.biblioteca.guardar()
        self.mix_timer.stop()
        self.mix_pausa_timer.stop()
        self._smooth_timer.stop()
        self.magnet_timer.stop()
        try: self.mixer.aur.cerrar()
        except Exception: pass
        self.mixer.stop()
        super().closeEvent(event)


def _mensajes_qt(tipo, ctx, msg):
    log("qt", msg)




def main(tiempos=None):
    t_ini = time.perf_counter()
    app = QApplication(sys.argv)
    try:
        from PySide6.QtCore import qInstallMessageHandler, __version__ as _qv
        qInstallMessageHandler(_mensajes_qt)             # los avisos internos de Qt también van a la consola
        import platform
        log("programa", f"AutoMix · Python {platform.python_version()} · PySide6 {_qv} · numpy {np.__version__} · {platform.platform()}")
        try:
            dev = sd.query_devices(sd.default.device[1] if sd.default.device[1] is not None and sd.default.device[1] >= 0 else None, "output")
            log("audio", f"salida: {dev['name']} · {int(dev['default_samplerate'])} Hz · {dev['max_output_channels']} canales")
        except Exception as e:
            log("audio", f"no se pudo leer el dispositivo de salida ({e})")
    except Exception:
        pass
    t_v0 = time.perf_counter()
    w = AutoMix()
    t_v1 = time.perf_counter()
    w.show()
    t_v2 = time.perf_counter()
    if tiempos:
        t0, t1, t2 = tiempos
        log("arranque", f"dependencias {t1 - t0:.2f} s · módulos {t2 - t1:.2f} s · Qt+audio {t_v0 - t_ini:.2f} s · armar ventana {t_v1 - t_v0:.2f} s · mostrar {t_v2 - t_v1:.2f} s · TOTAL {t_v2 - t0:.2f} s")
    log("programa", f"listo · biblioteca {w.biblioteca.count()} tema(s) · duración de mezcla {w.spin_mix.value()} s")
    sys.exit(app.exec())
