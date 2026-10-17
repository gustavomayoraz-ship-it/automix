"""AutoMix — botón Mezclar (F2), auto-enganche y reproducción."""
import sys
import time
from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox
from PySide6.QtCore import QTimer
from setup.ajustes import fmt_time
from setup.analisis import compat_armonica
from setup.base import _log_diferido, log
from setup.config import guardar_config


class MezclaMixin:
    """Botón Mezclar (F2), auto-enganche y reproducción (parte de la ventana principal)."""


    # ================= MEZCLA CON PAUSA AL 50% =================
    def _f2_global_cambio(self, activo, guardar=True):
        if activo:
            if not self.f2_global.registrar() and sys.platform == "win32":
                try: self._set_status("⚠️ F2 ya lo usa otro programa: solo funciona con AutoMix en primer plano")
                except Exception: print("[F2] otro programa ya usa F2: solo funciona con AutoMix en primer plano")
        else:
            self.f2_global.quitar()
        if guardar:
            try: guardar_config(f2_global=bool(activo))
            except Exception: pass

    def _mix_clicked(self):
        if self.mix_pausa_timer.isActive():          # en la pausa del 50 %: seguir ya, sin invertir el sentido
            self.mix_pausa_timer.stop()
            self._reanudar_mix()
            return
        if self.mix_timer.isActive():                # ya hay una mezcla en curso: no reiniciarla
            return
        current = self.crossfader.value()
        if current <= 50:
            target = 100
            direction = "A → B"
        else:
            target = 0
            direction = "B → A"

        entra = self.deck_b if target == 100 else self.deck_a
        if entra.audio is None:
            self._mix_auto = False
            self._set_status(f"⚠️ Cargá un tema en Deck {entra.name}")
            return
        if not entra.analysis:               # sin grilla no se puede emparejar: se espera a que termine el análisis
            n = getattr(self, "_mix_espera_n", 0)
            if n < 360:                      # hasta ~90 s
                if n == 0:
                    self._mix_esperando = True
                self._mix_espera_n = n + 1
                self._set_status(f"⏳ Esperando el análisis del Deck {entra.name} para mezclar emparejado…")
                QTimer.singleShot(250, self._mix_clicked)
                return
        self._mix_espera_n = 0
        self._mix_esperando = False
        entra.pos_manual = False
        entra.tempo_manual = False                   # al mezclar, el entrante vuelve a seguir al sync
        simple = self._cruce_simple()
        if simple:                           # BPM muy distintos: sin emparejar nada, solo se arranca el entrante
            if not entra.playing:
                entra.play()
            print(f"[mezcla] BPM muy distintos ({self.deck_a.original_bpm:.0f} / {self.deck_b.original_bpm:.0f}): cruce simple")
        else:
            if not entra.playing:
                entra.play()                     # al arrancar, _auto_sync ya lo alinea
            else:
                self._auto_sync(entra)           # ya sonaba (en espera): al empezar la mezcla se alinea A LA FUERZA
            self._alinear_ya(entra)              # y se confirma con el primer downbeat, antes de que se escuche

        self._cf_dir = "AB" if target == 100 else "BA"
        self.mix_from = current
        self.mix_to = target

        auto = bool(getattr(self, "_mix_auto", False)); self._mix_auto = False
        sale_d = self.deck_a if entra is self.deck_b else self.deck_b
        duration_s = self._duracion_mezcla_para(sale_d, entra, auto)
        if auto:
            ks, ke = self._clave_de(sale_d), self._clave_de(entra)
            nivel = compat_armonica(ks, ke)
            marca = {2: "✔ compatibles", 1: "≈ vecinas", 0: "✖ chocan → mezcla corta"}.get(nivel, "")
            print(f"[mezcla] {ks or '?'} → {ke or '?'} {marca} · {duration_s:.1f} s")
        interval_ms = 50
        self.mix_steps_total = int(duration_s * (1000.0 / interval_ms))
        self.mix_steps_done = 0
        self._mix_pausa_hecha = bool(simple)     # cruce simple: sin la pausa de 3 s al 50 % (con dos tempos distintos suena mal)
        self.mix_pausa_timer.stop()

        self._plan = None
        if self.recetas and self.cruce_ab and self.cruce_bandas and not simple:
            try:
                self._plan = self._planificar_mezcla(sale_d, entra, duration_s)
            except Exception:
                import traceback; traceback.print_exc()
                self._plan = None
        if self._plan:
            pl = self._plan
            print(f"[receta] {pl['nombre']} · sale desde {pl['pa']:.0%}, entra desde {pl['pb']:.0%}, bajo en {pl['ps']:.0%}")
        self.mix_timer.start(interval_ms)
        self._set_status(f"🎬 Mezclando {direction} en {int(duration_s)} s..." + (f"  🧠 {self._plan['nombre']}" if self._plan else ""))

    def _mix_step(self):
        if self.mix_steps_done >= self.mix_steps_total:
            self.mix_timer.stop()
            self.crossfader.setValue(self.mix_to)
            self._plan = None
            log("mezcla", f"completada · A {self.deck_a.position_seconds():.1f} s / B {self.deck_b.position_seconds():.1f} s")
            self._set_status("🎬 Mezcla completada")
            return

        self.mix_steps_done += 1
        frac = self.mix_steps_done / self.mix_steps_total
        value = int(round(self.mix_from + (self.mix_to - self.mix_from) * frac))

        if not self._mix_pausa_hecha:
            prev = self.crossfader.value()
            cruzando = (prev < 50 <= value) or (prev > 50 >= value)
            if cruzando:
                self.crossfader.setValue(50)
                self._mix_pausa_hecha = True
                self.mix_timer.stop()
                self._set_status("⏸ Mezcla pausada 3 s en el 50%…")
                self.mix_pausa_timer.start(3000)
                return

        self.crossfader.setValue(value)

    def _reanudar_mix(self):
        if self.mix_steps_done < self.mix_steps_total:
            self._set_status("🎬 Mezcla reanudada")
            self.mix_timer.start(50)

    # ================= PAUSA/PLAY CON ESPACIO =================
    def _toggle_play_pausa(self):
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QSpinBox)):
            return
        prim = self._deck_primario()
        if prim is None or prim.audio is None:
            self._set_status("▶ No hay deck cargado para pausar/reanudar")
            return
        if prim.playing:
            prim.pause()
            self._set_status(f"⏸ Deck {prim.name} pausado (Espacio)")
        else:
            prim.play()
            self._set_status(f"▶ Deck {prim.name} reanudado (Espacio)")

    # ================= AUTO-ENGANCHE =================
    def _deck_primario(self):
        a, b = self.deck_a, self.deck_b
        a_ok = a.playing and a.audio is not None
        b_ok = b.playing and b.audio is not None
        if a_ok and b_ok:
            return a if self.crossfader.value() < 50 else b
        if a_ok: return a
        if b_ok: return b
        f = self.crossfader.value()
        if f < 50 and a.audio is not None:
            return a
        if f >= 50 and b.audio is not None:
            return b
        if a.audio is not None: return a
        if b.audio is not None: return b
        return None

    def _marca_cambiada(self, f):
        self._marca_frac = float(f)
        self._marca_pendiente = False
        _log_diferido("marca", "auto-enganche", f"marca en {self._marca_frac * 100:.1f} %")
        self._marca_disparada = False
        prim = self._deck_primario()
        if prim is not None and prim.analysis and prim.analysis.get("duration", 0) > 0:
            d = float(prim.analysis["duration"]); fin = self._fin_audible(prim)
            d = min(d, fin) if fin > 1.0 else d
            self._ultimo_prog_primario = min(1.0, prim.position_seconds() / d)
        else:
            self._ultimo_prog_primario = 0.0
        guardar_config(marca_frac=self._marca_frac)
        self._actualizar_lbl_marca()

    def _marca_cruzada(self, f):
        pass

    def _actualizar_lbl_marca(self):
        if not hasattr(self, "lbl_marca"):
            return
        self.lbl_marca.setText(f"⚓ Marca: {self._marca_frac * 100:.1f}%\nDoble clic para restablecer")

    UMBRAL_SILENCIO = 0.004        # ≈ -48 dBFS: por debajo de esto se considera silencio
    SILENCIO_MIN = 3.0             # el silencio del final tiene que durar al menos esto (s) para tenerlo en cuenta

    def _fin_audible(self, deck):
        """Segundo en que termina la música del tema (sin el silencio del final). Si no hay silencio final largo,
        devuelve la duración completa. Se calcula una vez por tema cargado."""
        a = deck.audio
        if a is None:
            return 0.0
        c = getattr(deck, "_fin_cache", None)
        if c is not None and c[0] is a:
            return c[1]
        sr = max(1, int(deck.sr))
        total = len(a) / sr
        fin = total
        try:
            import numpy as np
            x = np.abs(a)
            if x.ndim > 1:
                x = x.max(axis=1)
            bloque = max(1, sr // 10)                    # bloques de 0,1 s
            n = len(x) // bloque
            if n > 0:
                pic = x[: n * bloque].reshape(n, bloque).max(axis=1)
                con = np.nonzero(pic > self.UMBRAL_SILENCIO)[0]
                ultimo = (int(con[-1]) + 1) * bloque / sr if len(con) else 0.0
                if total - ultimo >= self.SILENCIO_MIN and ultimo > 5.0:
                    fin = ultimo + 0.5                   # un resto de cola
                    log("silencio", f"deck {deck.name}: la música termina en {fmt_time(fin)}; "
                                    f"los últimos {fmt_time(total - fin)} son silencio")
        except Exception:
            fin = total
        deck._fin_cache = (a, fin)
        return fin

    def _tick_auto_enganche(self):
        prim = self._deck_primario()

        if prim is not self._ultimo_deck_primario:
            self._ultimo_deck_primario = prim
            self._marca_pendiente = False
            self._marca_disparada = False
            self._ultimo_prog_primario = 0.0

        if prim is None or not prim.analysis or prim.analysis.get("duration", 0) <= 0:
            self.barra_prog.set_progreso(0.0, 0.0, 0.0)
            return

        dur = float(prim.analysis["duration"])
        seg = float(prim.position_seconds())
        prog_barra = max(0.0, min(1.0, seg / dur if dur > 0 else 0.0))
        self.barra_prog.set_progreso(prog_barra, seg, dur)
        # La marca se mide sobre la parte CON música: si el tema trae silencio al final, no se espera a que pase.
        fin = self._fin_audible(prim)
        dur_ef = min(dur, fin) if fin > 1.0 else dur
        prog = max(0.0, min(1.0, seg / dur_ef if dur_ef > 0 else 0.0))

        if self._marca_frac >= 0 and not self._marca_disparada:
            if self._ultimo_prog_primario < self._marca_frac <= prog:
                self._marca_pendiente = True; self._marca_t_reintento = 0.0
                log("auto-enganche", f"marca {self._marca_frac * 100:.1f} % cruzada en {fmt_time(seg)} de {fmt_time(dur)}")
                self._set_status(
                    f"⚓ Auto-enganche disparado (marca {self._marca_frac * 100:.1f}%) → mezcla"
                )
            elif (not getattr(self, "_marca_pendiente", False) and dur_ef < dur - 0.5 and seg >= dur_ef
                  and prim.playing and not (self.mix_timer.isActive() or self.mix_pausa_timer.isActive())):
                # entró (o saltó) directo al silencio del final sin cruzar la marca: se mezcla igual
                self._marca_pendiente = True; self._marca_t_reintento = 0.0
                log("auto-enganche", "silencio al final del tema → mezcla")
                self._set_status("🔇 Silencio al final del tema → mezcla")
            if getattr(self, "_marca_pendiente", False):
                # Si al cruzar la marca no se pudo arrancar (el otro deck aún sin análisis/tonalidad, sin tema cargado…),
                # se reintenta cada segundo hasta que la mezcla arranque (antes se perdía y el tema se pasaba de largo).
                ahora = time.monotonic()
                if ahora >= getattr(self, "_marca_t_reintento", 0.0):
                    self._marca_t_reintento = ahora + 1.0
                    try:
                        self._disparar_mezcla_auto(exacto=True)      # la marca roja manda: se engancha JUSTO ahí, sin esperar frase
                    except Exception:
                        import traceback; traceback.print_exc()
                    if (self.mix_timer.isActive() or self.mix_pausa_timer.isActive()
                            or getattr(self, "_mix_esperando", False) or getattr(self, "_frase_armada", False)):
                        self._marca_pendiente = False; self._marca_disparada = True
                        log("auto-enganche", "mezcla arrancada")

        self._ultimo_prog_primario = prog

    def _vigilar_salida(self):
        """Si se desenchufó la placa/DAC USB, la salida pasa sola a la predeterminada de Windows."""
        m = self.mixer
        ahora = time.monotonic()
        if ahora - getattr(self, "_t_vig_sal", 0) >= 0.5:
            self._t_vig_sal = ahora
            m.vigilar_salida()
        try:
            self._aur_auto_dispositivos()
        except Exception:
            import traceback; traceback.print_exc()
        msg, m._aviso_salida = m._aviso_salida, None
        if msg:
            log("audio", msg)
            self._set_status(msg)
        if getattr(m, "aur_perdida", False):
            m.aur_perdida = False
            try:
                for b in self.btn_cue.values():
                    b.setChecked(False)
                for nom, b in getattr(self, "btn_prev", {}).items():
                    b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
                self._aur_refrescar()
            except Exception:
                pass

    def _vigilar_cortes_audio(self):
        """Avisa en la consola cuando la salida principal se queda sin audio (trancada) o un bloque tarda demasiado.
        Además consume la bandera de error del callback (que NUNCA debe imprimir por su cuenta)."""
        m = self.mixer
        # errores del callback: el callback solo marca, la UI imprime
        e = m._err_flag
        if e:
            m._err_flag = 0
            log("audio", f"⚠ error en el callback de audio ({m.ERR.get(e, e)}): esa parte se desactivó para no cortar el sonido")
        n = m.cortes_audio
        if n != getattr(self, "_cortes_vistos", 0):
            log("audio", f"⚠ corte de audio en la salida principal (van {n}) · bloque más lento: {m.cb_max_ms:.0f} ms"
                         f" (el límite es {m.blocksize / m.sr * 1000:.0f} ms)")
            self._cortes_vistos = n
            m.cb_max_ms = 0.0
        elif m.cb_max_ms > 0.8 * m.blocksize / m.sr * 1000 and time.monotonic() - getattr(self, "_t_lento", 0) > 5:
            log("audio", f"un bloque de audio tardó {m.cb_max_ms:.0f} ms (el límite es {m.blocksize / m.sr * 1000:.0f} ms): casi se corta")
            self._t_lento = time.monotonic()
            m.cb_max_ms = 0.0

    def _tick(self):
        self.deck_a.tick()
        self.deck_b.tick()
        self._vigilar_cortes_audio()
        self._vigilar_salida()
        self._mb_actualizar_barras()
        try:
            self._animar_cruce()
        except Exception:
            import traceback; traceback.print_exc()
        prim = self._deck_primario()
        rutas = (self.deck_a.path, self.deck_b.path, self.biblioteca.count(), prim.path if prim is not None else None,
                 self._clave_de(prim))
        if rutas != getattr(self, "_rutas_pintadas", None):
            self._rutas_pintadas = rutas
            self.biblioteca.set_referencia(rutas[4])
            self.biblioteca.pintar(self.deck_a.path, self.deck_b.path)
            if self.chk_armonico.isChecked() or self.chk_frases.isChecked():
                self._reordenar_pronto(400)               # la cadena sigue al tema que suena
        try:
            self._auto_vigilar()
        except Exception:
            import traceback; traceback.print_exc()
        try:
            self._vigilar_sync()
        except Exception:
            import traceback; traceback.print_exc()
        try:
            self._tick_auto_enganche()
        except Exception:
            import traceback; traceback.print_exc()
        self.timeline.redraw()

    _QSS_MIX_BASE = (
        "QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffd84a, stop:1 #ff9a00); color:#2a1700; font-weight:bold;"
        " border:1px solid #ffe08a; border-radius:11px; }"
        "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffe473, stop:1 #ffae2e); }"
        "QPushButton:pressed { background:#d98400; padding-top:2px; }"
        "QPushButton:disabled { background:#3a3322; color:#7a7155; border-color:#4a422c; }")

    def _animar_cruce(self):
        """Los decks brillan según cuánto suenan y el botón Mezclar muestra el avance de la mezcla."""
        try:
            self._loop_actualizar_ui()
        except Exception:
            pass
        for d in (self.deck_a, self.deck_b):
            peso = max(d.vol_hi, d.vol_lo) if d.playing else 0.0
            paso = int(round(peso * 10))
            if paso != d._glow_paso:
                d._glow_paso = paso
                d.set_brillo(paso / 10.0)
        mezclando = self.mix_timer.isActive() or self.mix_pausa_timer.isActive()
        if mezclando and self.mix_steps_total > 0:
            pct = max(0, min(100, int(round(100.0 * self.mix_steps_done / self.mix_steps_total))))
            clave = pct // 2
            if clave != getattr(self, "_mix_prog_clave", None):
                self._mix_prog_clave = clave
                p = clave * 0.02
                self.btn_mix.setStyleSheet(
                    "QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ffd84a, stop:%.3f #ff9a00, stop:%.3f #2b2112, stop:1 #1c160b);"
                    " color:#ffffff; font-weight:bold; border:1px solid #ffe08a; border-radius:11px; }" % (p, min(1.0, p + 0.002)))
                self.btn_mix.setText(f"⏳ Mezclando…  {pct} %")
        elif getattr(self, "_mix_prog_clave", None) is not None:
            self._mix_prog_clave = None
            self.btn_mix.setStyleSheet(self._QSS_MIX_BASE)
            self.btn_mix.setText(f"🎬 Mezclar ({self.spin_mix.value()}s) [F2]")
