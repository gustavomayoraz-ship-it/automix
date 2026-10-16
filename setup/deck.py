"""AutoMix — un deck (reproductor con su onda, tempo y rejilla)."""
from pathlib import Path
import math
import os
import threading
import time
import numpy as np
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout
from PySide6.QtCore import QPoint, QTimer, Qt
from setup.ajustes import NIVEL_V2, SUPPORTED, TARGET_LUFS_RMS, fmt_time
from setup.analisis import _guardar_cache, _limpiar_grilla_cache, _mantener_vivo, desfase_rejilla_bombos, desplazar_rejilla, grilla_manual, load_audio_stereo, plegar_bpm
from setup.base import CACHE_DIR, _log_diferido, log
from setup.hilos_analisis import Analyzer
from setup.tema import TEMA, _rgba
from setup.widgets import EtiquetaTema, RelojReset
from setup.wsola import WsolaFlujo


class Deck(QFrame):
    def __init__(self, name, color, on_analysis_cb):
        super().__init__()
        self.name = name
        self.on_analysis_cb = on_analysis_cb
        self.path = None
        self.analysis = None
        self.audio = None
        self.sr = 44100
        self.cursor = 0
        self._cursor_frac = 0.0
        self.playing = False
        self.vol_hi = 1.0; self.vol_lo = 1.0      # ganancia de medios+agudos y de graves (la aplica el mezclador, por bandas)
        self._db_cache = None
        self.volume = 1.0          # volumen de cada deck fijo al 100 %: el nivel se maneja con el crossfader y el volumen general
        self.auto_gain = 1.0
        self.tempo_rate = 1.0
        self.pos_manual = False     # el usuario ubicó el tema con la manito: la mezcla automática lo respeta
        self.tempo_manual = False   # el usuario fijó el tempo a mano: nada lo toca hasta que mezcle o apriete Reset
        self.trim = 1.0
        self.on_play_cb = None
        self.on_reset_cb = None
        self.lock = threading.Lock()
        self.original_bpm = None
        self._ws = WsolaFlujo(); self._ws_activo = False; self._ws_exp = None      # estirado de tiempo sin cambiar el tono
        self._ws_modo = False

        self.setAcceptDrops(True)
        self._acento = color
        self.setProperty("cargado", False)
        self.setStyleSheet(self._qss_deck(color))
        efecto = QGraphicsDropShadowEffect(self)
        efecto.setBlurRadius(34); efecto.setOffset(0, 3); efecto.setColor(QColor(_rgba(color, 120)))
        self.setGraphicsEffect(efecto)
        self._efecto = efecto
        self._glow_paso = -1
        self.setFixedHeight(150)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(3)

        r1 = QHBoxLayout()
        self.lbl_title = QLabel(f"DECK {name}")
        self.lbl_title.setStyleSheet(f"color:{color}; font-size:16px; font-weight:bold;")
        self.lbl_title.setFixedWidth(112)
        r1.addWidget(self.lbl_title)
        self.lbl_track = EtiquetaTema("Arrastrá una canción aquí")
        self.on_ubicar_cb = None
        self.lbl_track.clicked.connect(lambda: self.on_ubicar_cb(self.path) if self.on_ubicar_cb else None)
        self.lbl_track.setStyleSheet(f"color:{TEMA['texto']}; font-size:11px;")
        r1.addWidget(self.lbl_track, stretch=1)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        self.lbl_bpm = QLabel("BPM: --")
        self.lbl_bpm.setStyleSheet(f"color:{TEMA['ambar']}; font-size:11px; font-weight:bold;")
        self.lbl_bpm.setFixedWidth(220)
        r2.addWidget(self.lbl_bpm)
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("color:#ffffff; font-size:12px; font-weight:bold;")
        r2.addWidget(self.lbl_time, stretch=1)
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(4)
        self.btn_load = QPushButton("📂")
        self.btn_play = QPushButton("▶")
        self.btn_pause = QPushButton("⏸")
        self.btn_stop = QPushButton("⏹")
        self.btn_reset = QPushButton("⟲")
        for b in (self.btn_load, self.btn_play, self.btn_pause,
                  self.btn_stop, self.btn_reset):
            b.setFixedHeight(38); b.setFixedWidth(58); r3.addWidget(b)
            fb = b.font(); fb.setPointSizeF(17.0); fb.setBold(True); b.setFont(fb)
        self.btn_play.setProperty("rol", "play"); self.btn_pause.setProperty("rol", "pausa"); self.btn_stop.setProperty("rol", "stop")
        self.btn_load.clicked.connect(self.load_dialog)
        self.btn_play.clicked.connect(self.play)
        self.btn_pause.clicked.connect(self.pause)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_reset.clicked.connect(lambda *_: self.reset_tempo(suave=True))
        self.btn_reset.setToolTip("Resetear el tempo al 100 % (el tema sigue donde está)")
        r3.addSpacing(6)
        r3.addWidget(QLabel("Tempo"))                    # el slider de tempo va en la misma fila, a la derecha del botón de reset
        self.sld_tempo = QSlider(Qt.Orientation.Horizontal)
        self.sld_tempo.setRange(50, 200); self.sld_tempo.setValue(100)
        self.sld_tempo.setMinimumWidth(70)
        r3.addWidget(self.sld_tempo, stretch=1)
        self._flechas_tempo = []
        self.reloj_reset = RelojReset(self, color)
        for txt, paso, tip in (("◀", -1, "Tempo −1 %"), ("▶", 1, "Tempo +1 %")):
            b = QPushButton(txt); self._flechas_tempo.append(b); b.setFixedSize(24, 24); b.setAutoRepeat(True); b.setAutoRepeatDelay(350); b.setAutoRepeatInterval(90)
            b.setToolTip(tip + "  (el tempo se mantiene hasta que mezcle o toques Reset)")
            b.setStyleSheet("QPushButton { padding:0px; font-size:11px; }")
            b.clicked.connect(lambda _=False, d=paso: self.sld_tempo.setValue(self.sld_tempo.value() + d))
            r3.addWidget(b)
        lay.addLayout(r3)

        self.sld_tempo.valueChanged.connect(self._update_tempo)

    @staticmethod
    def _qss_deck(color):
        c = QColor(color); h = max(0, c.hue())
        f1 = QColor.fromHsv(h, 210, 104).name(); f2 = QColor.fromHsv(h, 190, 48).name()
        f3 = QColor.fromHsv(h, 165, 19).name()
        osc = QColor.fromHsv(h, 230, 150).name()
        return (
            f"Deck {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {f1}, stop:0.55 {f2}, stop:1 {f3});"
            f" border:1px dashed {_rgba(color, 150)}; border-radius:14px; }}"
            f"Deck[cargado=\"true\"] {{ border:1px solid {_rgba(color, 230)}; }}"
            f"Deck QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {osc}, stop:1 {color}); border-radius:4px; }}"
            f"Deck QSlider::handle:horizontal {{ border:2px solid {color}; }}"
        )

    def set_brillo(self, peso):
        """Resplandor del deck según cuánto está sonando (0..1): se enciende el que entra y se apaga el que sale."""
        peso = max(0.0, min(1.0, float(peso)))
        c = QColor(self._acento)
        self._efecto.setColor(QColor(c.red(), c.green(), c.blue(), int(45 + 150 * peso)))
        self._efecto.setBlurRadius(18 + 26 * peso)

    def _marcar_cargado(self, v):
        self.setProperty("cargado", bool(v))
        self.style().unpolish(self); self.style().polish(self)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isfile(p) and p.lower().endswith(SUPPORTED):
                self.load_track(p)
                break

    def load_dialog(self):
        f, _ = QFileDialog.getOpenFileName(
            self, f"Cargar en Deck {self.name}", "", "Audio (*.mp3 *.wav *.flac *.ogg *.m4a)"
        )
        if f:
            self.load_track(f)

    def descargar(self):
        """Deck vacío: como recién abierto el programa (sin tema, sin análisis, tempo al 100 %)."""
        self._cancelar_reset_suave()
        self.stop()
        with self.lock:
            self.audio = None
            self.cursor = 0
            self._cursor_frac = 0.0
        self.analysis = None
        self.original_bpm = None
        self.path = None
        self.auto_gain = 1.0
        self._ag_listo = False
        self._db_cache = None
        self.tempo_rate = 1.0
        self.tempo_manual = False
        self.pos_manual = False
        self.trim = 1.0
        if self.sld_tempo.value() != 100:
            self.sld_tempo.blockSignals(True); self.sld_tempo.setValue(100); self.sld_tempo.blockSignals(False)
        self._marcar_cargado(False)
        self.lbl_track.setText("Arrastrá una canción aquí"); self.lbl_track.setToolTip("")
        self.lbl_bpm.setText("BPM: --")
        self.lbl_time.setText("00:00 / 00:00")
        log(f"deck {self.name}", "vaciado")

    def load_track(self, path):
        self.stop()
        self.pos_manual = False
        with self.lock:
            self.audio = None
            self.cursor = 0
            self._cursor_frac = 0.0
            self._ws_activo = False
        self.analysis = None
        self.original_bpm = None
        self.auto_gain = 1.0
        self._ag_listo = False
        self.path = path
        log(f"deck {self.name}", f"cargando: {os.path.basename(path)}")
        self._marcar_cargado(True)
        self.lbl_track.setText(os.path.basename(path))
        self.lbl_bpm.setText("⏳ Analizando…")
        self.analyzer = Analyzer(path)
        _mantener_vivo(self.analyzer)
        self.analyzer.done.connect(self._on_analysis)
        self.analyzer.start()
        threading.Thread(target=self._load_audio, args=(path,), daemon=True).start()

    def _load_audio(self, path):
        try:
            y, sr = load_audio_stereo(path, sr=44100)
            # TODO lo pesado (copia contigua, Auto-Gain) FUERA del lock: el lock del deck lo toma
            # también el callback de audio, y si se queda esperando se oye un corte en lo que suena.
            y32 = np.ascontiguousarray(y, dtype=np.float32)
            ag = self._calc_auto_gain(y32)
            with self.lock:
                if path != self.path:
                    return
                self.auto_gain = ag
                self._ag_listo = True
                self.audio = y32
                self.sr = sr
                self.cursor = 0
                self._cursor_frac = 0.0
            log(f"deck {self.name}", f"audio listo: {len(y32) / sr:.1f} s · {sr} Hz · auto-gain x{ag:.2f} · {os.path.basename(path)}")
        except Exception as e:
            print("Error cargando audio:", e)

    @staticmethod
    def _calc_auto_gain(audio):
        """Auto-Gain a partir del audio ya cargado (sin librosa ni re-análisis)."""
        try:
            n = (len(audio) // 1024) * 1024
            if n < 2048:
                return 1.0
            # media L/R por bloques de 1024, sin copias gigantes de float64
            bloques = audio[:n].reshape(-1, 1024, 2)
            e = np.einsum("bij,bij->b", bloques, bloques, dtype=np.float64) / (1024 * 2)
            rms_medio = float(np.mean(np.sqrt(e)))
            return float(np.clip(TARGET_LUFS_RMS / rms_medio, 0.25, 4.0)) if rms_medio > 1e-6 else 1.0
        except Exception:
            return 1.0

    @staticmethod
    def _afinar_bpm(res):
        """El BPM global de librosa suele errar 1-2 %. Con la grilla de beats detectada se calcula uno
        mucho más preciso (media de los intervalos sin los atípicos). Un error de 1 % en el BPM
        hace que, en una mezcla de 10 s, los golpes se corran ~100 ms y se oiga doble (flam)."""
        try:
            b = np.asarray(res.get("beats_full") or [], dtype=np.float64)
            if len(b) < 16:
                return
            iv = np.diff(b)
            m = float(np.median(iv))
            k = iv[np.abs(iv - m) < 0.08 * m]
            if len(k) < 12 or m <= 0:
                return
            fino = 60.0 / float(np.mean(k))
            if abs(fino - res["bpm"]) / res["bpm"] < 0.03:      # solo afina; no cambia de "mitad/doble"
                res["bpm_librosa"] = res["bpm"]
                res["bpm"] = float(fino)
        except Exception:
            pass

    def _on_analysis(self, path, res):
        if path != self.path:
            return
        if "error" in res:
            self.lbl_bpm.setText("Error")
            return
        _limpiar_grilla_cache(res)
        self._afinar_bpm(res)
        if plegar_bpm(res):                                   # BPM absurdo (p. ej. 1535): se lleva al rango musical y se guarda
            log(f"deck {self.name}", f"BPM fuera de rango corregido → {res['bpm']:.1f}")
            try:
                _guardar_cache(CACHE_DIR / (Path(self.path).stem + ".json"), res)
            except Exception:
                pass
        self.analysis = res
        self.original_bpm = res["bpm"]
        if not getattr(self, "_ag_listo", False):
            self.auto_gain = res.get("auto_gain", 1.0)
        self._update_bpm_label()
        self.lbl_time.setText(f"00:00 / {fmt_time(res['duration'])}")
        if self.on_analysis_cb:
            self.on_analysis_cb(self.name, res)

    def centrar_rejilla(self, avisar=True):
        """Mueve la grilla para que los tiempos caigan sobre los bombos. Devuelve el corrimiento en ms (None = no se pudo medir)."""
        if not self.analysis or not self.path:
            return None
        off = desfase_rejilla_bombos(self.analysis)
        if off is None:
            return None
        if abs(off) < 0.008:                              # ya está bien centrada (menos de 8 ms)
            return 0.0
        with self.lock:
            desplazar_rejilla(self.analysis, off)
            self._db_cache = None
        try:
            _guardar_cache(CACHE_DIR / (Path(self.path).stem + ".json"), self.analysis)
        except Exception:
            import traceback; traceback.print_exc()
        if avisar and self.on_analysis_cb:
            self.on_analysis_cb(self.name, self.analysis)
        return off * 1000.0

    def corregir_rejilla(self, factor=1.0, uno_en=None, usuario=False, avisar=True):
        """Botones ÷2 / ×2 / ①. Cambia la grilla del tema cargado, la guarda en su caché y avisa a la ventana."""
        if not self.analysis or not self.path:
            return False
        try:
            with self.lock:
                try:
                    grilla_manual(self.analysis, factor, uno_en)
                except ValueError as e:
                    self.motivo_rechazo = str(e)
                    return False
                if usuario:
                    self.analysis["usuario"] = True          # la corrigió el usuario: el modo Auto ya no la toca
                self.original_bpm = self.analysis["bpm"]
                self._db_cache = None
            self._update_bpm_label()
            try:
                _guardar_cache(CACHE_DIR / (Path(self.path).stem + ".json"), self.analysis)
            except Exception:
                import traceback; traceback.print_exc()
            if avisar and self.on_analysis_cb:
                self.on_analysis_cb(self.name, self.analysis)
            return True
        except Exception:
            import traceback; traceback.print_exc()
            return False

    def _update_bpm_label(self):
        if self.original_bpm is None:
            return
        eff = self.original_bpm * self.tempo_rate
        self.lbl_bpm.setText(f"BPM: {eff:6.2f} (AutoGain: {self.auto_gain:.2f}x)")

    @property
    def rate_eff(self):
        return self.tempo_rate * self.trim

    def play(self):
        if self.audio is None:
            return
        if self.on_play_cb is not None and not self.playing:
            try:
                self.on_play_cb(self)
            except Exception:
                import traceback; traceback.print_exc()
        if not self.playing:
            log(f"deck {self.name}", f"▶ play · {self.lbl_bpm.text().replace(chr(10), ' ')} · tempo {self.tempo_rate * 100:.0f} %")
        self.playing = True

    def pause(self):
        if self.playing:
            log(f"deck {self.name}", f"⏸ pausa en {self.position_seconds():.1f} s")
        self.playing = False

    def stop(self):
        if self.playing:
            log(f"deck {self.name}", "⏹ stop")
        self.playing = False
        self.trim = 1.0
        with self.lock:
            self.cursor = 0
            self._cursor_frac = 0.0
            self._ws_activo = False

    RESET_SUAVE_S = 3.0          # el botón Reset vuelve al 100 % progresivamente (si el tema está sonando)

    def _ubicar_reloj(self):
        """Lo deja centrado justo arriba de las dos flechitas."""
        a, b = self._flechas_tempo
        c = a.mapTo(self, QPoint(0, 0)); d = b.mapTo(self, QPoint(b.width(), 0))
        self.reloj_reset.move((c.x() + d.x() - self.reloj_reset.width()) // 2, c.y() - self.reloj_reset.height() - 3)
        self.reloj_reset.raise_()

    def _paso_reset_suave(self):
        k = min(1.0, (time.monotonic() - self._rs_t0) / self.RESET_SUAVE_S)
        self.reloj_reset.set_progreso(k)
        e = 0.5 - 0.5 * math.cos(k * math.pi)                      # arranca y termina despacio
        self.tempo_rate = self._rs_r0 + (1.0 - self._rs_r0) * e
        pct = int(round(self.tempo_rate * 100))
        if self.sld_tempo.value() != pct:
            self.sld_tempo.blockSignals(True); self.sld_tempo.setValue(pct); self.sld_tempo.blockSignals(False)
        self._update_bpm_label()
        if k >= 1.0:
            self._rs_timer.stop(); self.tempo_rate = 1.0
            self._update_bpm_label()
            QTimer.singleShot(350, lambda: None if self._rs_timer.isActive() else self.reloj_reset.hide())   # un instante completo y se va

    def _cancelar_reset_suave(self):
        t = getattr(self, "_rs_timer", None)
        if t is not None and t.isActive():
            t.stop()
        t = getattr(self, "_aj_timer", None)
        if t is not None and t.isActive():
            t.stop()
        self._aj_gen = getattr(self, "_aj_gen", 0) + 1
        self.reloj_reset.hide()

    # ---- reloj del AJUSTE AUTOMÁTICO de velocidad (sync / auto-enganche): el mismo relojito del Reset ----
    def _reset_activo(self):
        t = getattr(self, "_rs_timer", None)
        return t is not None and t.isActive()

    def mostrar_ajuste(self, k):
        """Muestra el reloj con el progreso k (0..1) del ajuste de velocidad que hace el programa solo."""
        if self._reset_activo():
            return
        self._aj_gen = getattr(self, "_aj_gen", 0) + 1            # cancela cualquier ocultamiento pendiente
        self.reloj_reset.set_progreso(k)
        if not self.reloj_reset.isVisible():
            self._ubicar_reloj(); self.reloj_reset.show()

    def ocultar_ajuste(self, demora=350):
        self._aj_gen = getattr(self, "_aj_gen", 0) + 1
        g = self._aj_gen
        def _h():
            if g == getattr(self, "_aj_gen", 0) and not self._reset_activo():
                self.reloj_reset.hide()
        QTimer.singleShot(demora, _h)

    def barrido_ajuste(self, dur=1.3):
        """El enganche cambió la velocidad de golpe: el reloj da una vuelta para que se note."""
        if self._reset_activo():
            return
        if getattr(self, "_aj_timer", None) is None:
            self._aj_timer = QTimer(self); self._aj_timer.setInterval(30)
            self._aj_timer.timeout.connect(self._paso_barrido)
        self._aj_t0 = time.monotonic(); self._aj_dur = float(dur)
        self.mostrar_ajuste(0.0)
        self._aj_timer.start()

    def _paso_barrido(self):
        k = min(1.0, (time.monotonic() - self._aj_t0) / max(0.05, self._aj_dur))
        self.mostrar_ajuste(0.5 - 0.5 * math.cos(k * math.pi))
        if k >= 1.0:
            self._aj_timer.stop()
            self.ocultar_ajuste()

    def reset_tempo(self, suave=False):
        """Solo vuelve el tempo al 100 % (y el microajuste a 1.0). NO toca la posición del tema.
        Con suave=True y el tema sonando, la vuelta es progresiva (desimulada) en vez de un salto."""
        self.trim = 1.0
        self.tempo_manual = False
        self._cancelar_reset_suave()
        if abs(self.tempo_rate - 1.0) > 1e-6:
            log(f"deck {self.name}", f"tempo {self.tempo_rate * 100:.0f} % → 100 % ({'progresivo' if suave and self.playing else 'inmediato'})")
        if suave and self.playing and abs(self.tempo_rate - 1.0) > 0.004:
            if getattr(self, "_rs_timer", None) is None:
                self._rs_timer = QTimer(self); self._rs_timer.setInterval(30)
                self._rs_timer.timeout.connect(self._paso_reset_suave)
            self._rs_r0 = self.tempo_rate; self._rs_t0 = time.monotonic()
            self.reloj_reset.set_progreso(0.0); self._ubicar_reloj(); self.reloj_reset.show()
            self._rs_timer.start()
        # Resetea el tempo_rate al 100% (slider incluido, sin disparar señales)
        elif abs(self.tempo_rate - 1.0) > 1e-6:
            self.tempo_rate = 1.0
            pct = 100
            if self.sld_tempo.value() != pct:
                self.sld_tempo.blockSignals(True)
                self.sld_tempo.setValue(pct)
                self.sld_tempo.blockSignals(False)
        self._update_bpm_label()
        # Avisar a la ventana (redibuja timeline, status, etc.)
        if self.on_reset_cb is not None:
            try:
                self.on_reset_cb(self)
            except Exception:
                import traceback; traceback.print_exc()

    reset_time = reset_tempo      # nombre anterior, por compatibilidad

    def _update_tempo(self):
        self._cancelar_reset_suave()
        self.tempo_rate = self.sld_tempo.value() / 100.0
        self.tempo_manual = (self.sld_tempo.value() != 100)      # (los cambios por programa bloquean la señal: esto es del usuario)
        _log_diferido(f"tempo{self.name}", f"deck {self.name}", f"tempo manual {self.sld_tempo.value()} % ({(self.original_bpm or 0) * self.tempo_rate:.1f} BPM)")
        self._update_bpm_label()

    def set_tempo_from_fader(self, rate):
        rate = float(np.clip(rate, 0.5, 2.0))
        self.tempo_rate = rate
        pct = int(round(rate * 100))
        if self.sld_tempo.value() != pct:
            self.sld_tempo.blockSignals(True)
            self.sld_tempo.setValue(pct)
            self.sld_tempo.blockSignals(False)
        self._update_bpm_label()

    def position_seconds(self):
        with self.lock:
            return self.cursor / self.sr if self.audio is not None else 0.0

    def set_position_seconds(self, t):
        if self.audio is None:
            return
        t = float(np.clip(t, 0.0, len(self.audio) / self.sr - 0.001))
        with self.lock:
            self.cursor = int(t * self.sr)
            self._cursor_frac = 0.0

    def tick(self):
        if self.analysis and self.audio is not None:
            pos = self.position_seconds()
            self.lbl_time.setText(f"{fmt_time(pos)} / {fmt_time(self.analysis['duration'])}")

    WSOLA = True            # False: las velocidades distintas de 1,0 cambian el tono (remuestreo, como un disco de vinilo)

    def _render_directo(self, frames, rate):
        """Lectura sin estirado: exacta a velocidad 1,0 y, si no, por remuestreo cúbico (cambia el tono)."""
        n_audio = len(self.audio)
        if abs(rate - 1.0) < 1e-9 and self._cursor_frac == 0.0:
            chunk = self.audio[self.cursor:self.cursor + frames]
            if len(chunk) < frames:
                pad = np.zeros((frames - len(chunk), 2), dtype=np.float32)
                chunk = np.vstack([chunk, pad])
                self.playing = False
            self.cursor += frames
            return chunk
        pos = self.cursor + self._cursor_frac + np.arange(frames, dtype=np.float64) * rate
        i1 = np.floor(pos).astype(np.int64)
        t = (pos - i1).astype(np.float32)[:, None]
        if i1[-1] + 2 >= n_audio:
            self.playing = (i1[0] + 2 < n_audio)
        idx = np.clip(np.stack([i1 - 1, i1, i1 + 1, i1 + 2]), 0, n_audio - 1)
        p0, p1, p2, p3 = (self.audio[idx[k]] for k in range(4))
        t2 = t * t; t3 = t2 * t
        y = 0.5 * ((2 * p1) + (-p0 + p2) * t
                   + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                   + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
        valid = (pos < n_audio - 1)[:, None]
        total = self._cursor_frac + frames * rate
        int_adv = int(total)
        self._cursor_frac = total - int_adv
        self.cursor += int_adv
        return (y * valid).astype(np.float32)

    WS_ENTRA = 0.020          # el estirado (WSOLA) se usa solo si la velocidad se aparta más de esto de 1,0 ...
    WS_SALE = 0.012           # ... y se abandona recién por debajo de esto (histéresis: no cambia de modo a cada rato)

    def _ws_usar(self, rate):
        """Con diferencias de velocidad chicas (< ~2 %) el WSOLA agrega un temblor leve y el remuestreo directo solo
        cambia el tono unos centésimos de semitono (imperceptible), así que ahí se lee directo."""
        d = abs(rate - 1.0)
        if d <= 1e-9:
            self._ws_modo = False
        elif self._ws_modo:
            self._ws_modo = d >= self.WS_SALE
        else:
            self._ws_modo = d > self.WS_ENTRA
        return self._ws_modo

    def _render_wsola(self, frames, rate):
        """Lectura con WSOLA: la velocidad cambia pero el tono se mantiene. El cursor sigue la posición real en el tema."""
        salto = False
        if not self._ws_activo or self._ws_exp != (self.cursor, self._cursor_frac):
            salto = self._ws_activo                                  # había estirado en marcha: es un salto de posición
            self._ws.reset(self.cursor + self._cursor_frac)          # arranque, o alguien movió el cursor (salto, manito…)
            self._ws_activo = True
        y, fin = self._ws.leer(self.audio, frames, float(np.clip(rate, 0.5, 2.0)))
        if salto:
            k = min(128, frames)
            y[:k] *= np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]      # entrada suave: sin chasquido al saltar
        h = self._ws.head
        self.cursor = int(h)
        self._cursor_frac = h - self.cursor
        self._ws_exp = (self.cursor, self._cursor_frac)
        if fin or self.cursor >= len(self.audio) - 2:
            self.playing = False
        return y

    def render(self, frames):
        out = np.zeros((frames, 2), dtype=np.float32)
        with self.lock:
            if not self.playing or self.audio is None:
                return out
            rate = self.rate_eff
            ganancia_total = self.auto_gain * NIVEL_V2   # el volumen (por bandas) lo aplica el mezclador
            try:
                if Deck.WSOLA and self._ws_usar(rate):
                    y = self._render_wsola(frames, rate)
                elif self._ws_activo:                    # deja el estirado (rate 1,0 o muy cerca): unos ms de fundido hacia la lectura directa
                    if self._ws_exp == (self.cursor, self._cursor_frac):
                        h0 = self._ws.head
                        y_ws, _ = self._ws.leer(self.audio, frames, float(np.clip(rate, 0.5, 2.0)))
                        self.cursor = int(h0); self._cursor_frac = h0 - self.cursor
                        y_d = self._render_directo(frames, rate)
                        f = np.linspace(0.0, 1.0, frames, dtype=np.float32)[:, None]
                        y = y_ws * (1.0 - f) + y_d * f
                    else:
                        y = self._render_directo(frames, rate)
                    self._ws_activo = False
                else:
                    y = self._render_directo(frames, rate)
            except Exception:
                import traceback; traceback.print_exc()
                Deck.WSOLA = False                       # ante cualquier fallo se vuelve al remuestreo de siempre
                self._ws_activo = False
                print("[audio] WSOLA desactivado por un error: se usa el remuestreo")
                y = self._render_directo(frames, rate)
            out[:] = y * ganancia_total
        return out
