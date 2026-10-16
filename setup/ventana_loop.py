"""AutoMix — loop: repetir un trozo del tema que suena (el "chiqui-chiqui") para soltar el otro tema encima."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton
from setup.base import log
from setup.config import guardar_config, leer_config
from setup.tema import TEMA
from setup.widgets import qss_marco


class LoopMixin:
    """Loop de 1/4, 1/2, 1 o 2 compases pegado a la grilla (parte de la ventana principal)."""
    LOOP_LARGOS = (("¼", 1, "Un golpe (¼ de compás)"), ("½", 2, "Dos golpes (½ compás)"),
                   ("1", 4, "Un compás"), ("2", 8, "Dos compases"))

    _QSS_LOOP_OFF = ("QPushButton { color:#ffd84a; font-weight:bold; padding:0px 6px; background:rgba(0,0,0,70);"
                     " border:1px solid #ffb82e; border-radius:7px; }"
                     "QPushButton:hover { background:rgba(255,184,46,45); }")
    _QSS_LOOP_ON = ("QPushButton { color:#2a1700; font-weight:bold; padding:0px 6px;"
                    " background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffd84a, stop:1 #ff9a00);"
                    " border:1px solid #ffe08a; border-radius:7px; }")
    _QSS_LOOP_N = ("QPushButton { color:#ffd84a; font-weight:bold; padding:0px; background:rgba(0,0,0,70);"
                   " border:1px solid #7a5a1e; border-radius:7px; }"
                   "QPushButton:hover { background:rgba(255,184,46,35); }"
                   "QPushButton:checked { background:#ffb82e; color:#2a1700; border-color:#ffe08a; }")

    def _crear_loop(self):
        self.marco_loop = QFrame()                      # cuadro con degradé ámbar
        self.marco_loop.setObjectName("marcoLoop")
        self.marco_loop.setStyleSheet(qss_marco("QFrame#marcoLoop", TEMA["ambar"], titulo=False).replace("border-radius:12px", "border-radius:9px"))
        fila = QHBoxLayout(self.marco_loop); fila.setContentsMargins(6, 3, 6, 3); fila.setSpacing(4)
        self._loop_deck = None
        self._loop_estilo = None
        self.btn_loop = QPushButton("🔁 Loop")
        self.btn_loop.setFixedHeight(26); self.btn_loop.setMinimumWidth(96)
        self.btn_loop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_loop.setStyleSheet(self._QSS_LOOP_OFF)
        self.btn_loop.setToolTip("Repite un trozo del tema que está sonando (pegado a los golpes de la grilla).\n"
                                 "Con el loop andando soltás el otro tema encima y se engancha al compás.\n"
                                 "Al soltar el loop, el tema sigue por donde estaría si nunca hubiera repetido.  [Tecla L]")
        self.btn_loop.clicked.connect(self._loop_alternar)
        fila.addWidget(self.btn_loop)
        self._grp_loop = QButtonGroup(self); self._grp_loop.setExclusive(True)
        pref = int(leer_config().get("loop_golpes", 4))
        self._loop_golpes = pref if pref in (1, 2, 4, 8) else 4
        for txt, n, tip in self.LOOP_LARGOS:
            b = QPushButton(txt); b.setCheckable(True); b.setFixedSize(30, 26)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus); b.setStyleSheet(self._QSS_LOOP_N); b.setToolTip(tip)
            b.setChecked(n == self._loop_golpes)
            b.clicked.connect(lambda _=False, n=n: self._loop_largo_cambio(n))
            self._grp_loop.addButton(b); fila.addWidget(b)
        self._sc_loop = QShortcut(QKeySequence(Qt.Key.Key_L), self)
        self._sc_loop.activated.connect(self._loop_alternar)
        return self.marco_loop

    def _loop_activo(self):
        d = self._loop_deck
        return d is not None and d.loop is not None

    def _loop_alternar(self):
        if self._loop_activo():
            d = self._loop_deck
            d.terminar_loop()
            log("loop", f"deck {d.name}: loop suelto")
            self._set_status(f"🔁 Deck {d.name}: loop suelto, el tema sigue en su compás")
            return
        d = self._deck_primario()
        if d is None or not d.playing or d.audio is None:
            self._set_status("🔁 Poné a sonar un tema para hacer el loop")
            return
        if not d.analysis:
            self._set_status("🔁 Esperá a que termine el análisis del tema (hace falta la grilla)")
            return
        if d.iniciar_loop(self._loop_golpes):
            self._loop_deck = d
            nombre = {1: "¼ compás", 2: "½ compás", 4: "1 compás", 8: "2 compases"}[self._loop_golpes]
            log("loop", f"deck {d.name}: loop de {nombre} ({d.loop[0] / d.sr:.2f}–{d.loop[1] / d.sr:.2f} s)")
            self._set_status(f"🔁 Deck {d.name}: loop de {nombre}. Soltá el otro tema encima; con L o el botón lo soltás")
        else:
            self._set_status("🔁 No se pudo hacer el loop acá (sin grilla o muy cerca del final)")

    def _loop_largo_cambio(self, n):
        self._loop_golpes = n
        guardar_config(loop_golpes=int(n))
        if self._loop_activo():                      # cambia el largo sin cortar el loop (la posición "virtual" se mantiene)
            d = self._loop_deck
            des = d.loop_desfase
            if d.iniciar_loop(n):
                d.loop_desfase = des

    def _loop_actualizar_ui(self):
        activo = self._loop_activo()
        if not activo:
            self._loop_deck = None
        clave = (activo, self._loop_deck.name if activo else "")
        if clave != self._loop_estilo:
            self._loop_estilo = clave
            self.btn_loop.setStyleSheet(self._QSS_LOOP_ON if activo else self._QSS_LOOP_OFF)
            self.btn_loop.setText(f"🔁 Loop {self._loop_deck.name} ●" if activo else "🔁 Loop")
