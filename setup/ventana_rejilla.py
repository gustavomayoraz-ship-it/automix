"""AutoMix — rejilla: edición manual y Auto-grilla."""
from pathlib import Path
from setup.ajustes import fmt_time
from setup.analisis import _guardar_cache, plegar_bpm
from setup.base import CACHE_DIR, log
from setup.config import guardar_config


class RejillaMixin:
    """Rejilla: edición manual y Auto-grilla (parte de la ventana principal)."""


    def _rejilla(self, deck, factor=1.0, uno=False):
        if not deck.analysis:
            self._set_status(f"⚠️ Deck {deck.name}: no hay un tema analizado")
            return
        t_uno = None
        if uno:
            t_uno = (deck.cursor + deck._cursor_frac) / float(deck.sr)
            try:                                  # sonando: lo que se oye va atrás de la posición por la latencia de la salida
                if deck.playing and self.mixer.stream is not None:
                    t_uno -= float(self.mixer.stream.latency) * max(1e-6, deck.rate_eff)
            except Exception:
                pass
            t_uno = max(0.0, t_uno)
        deck.motivo_rechazo = None
        if deck.corregir_rejilla(factor=factor, uno_en=t_uno, usuario=True):
            msg = ("BPM ×2" if factor == 2.0 else "BPM ÷2") if not uno else f"el 1 queda en {fmt_time(t_uno)}"
            log(f"deck {deck.name}", f"rejilla: {msg} → {deck.analysis['bpm']:.2f} BPM")
            self._set_status(f"🎯 Deck {deck.name}: {msg} · {deck.analysis['bpm']:.1f} BPM (guardado)")
        elif getattr(deck, "motivo_rechazo", None):
            self._set_status(f"⚠️ Deck {deck.name}: no se cambió, {deck.motivo_rechazo}")

    def _estilo_auto_rej(self):
        on = self.btn_auto_rej.isChecked()
        self.btn_auto_rej.setText("Auto ON" if on else "Auto OFF")
        col, fondo = ("#2ee59d", "#0f5a3c") if on else ("#ff5a6a", "#5a1620")
        self.btn_auto_rej.setStyleSheet(f"QPushButton {{ padding:0px 2px; font-size:13px; font-weight:bold; color:#ffffff;"
                                        f" background:{fondo}; border:2px solid {col}; border-radius:8px; }}")

    def _auto_rej_cambio(self, on):
        self._estilo_auto_rej()
        guardar_config(auto_grilla=bool(on))
        log("rejilla", "auto-grilla " + ("ACTIVADA" if on else "DESACTIVADA") + " (se cambió el botón)")
        if on:
            self._rej_visto = {}
            self._t_auto_rej.start()
            self._auto_rejilla(forzar=True)
        else:
            self._t_auto_rej.stop()
            self.lbl_rej.setText("Auto-grilla desactivada")
            log("rejilla", "auto-grilla desactivada")
            self._set_status("🎯 Auto-grilla desactivada")

    def _vigilar_rejilla(self):
        """Con Auto activado: cada vez que entra un tema nuevo (o termina su análisis) se revisa y empareja su grilla."""
        try:
            nuevo = False
            for d in (self.deck_a, self.deck_b):
                clave = (d.path, id(d.analysis)) if d.analysis else None
                if clave is not None and self._rej_visto.get(d.name) != clave:
                    nuevo = True
            if nuevo:
                self._auto_rejilla()
        except Exception:
            import traceback; traceback.print_exc()

    def _auto_rejilla(self, forzar=False):
        """Botón 🎯 Auto. Para los dos temas cargados: (1) corrige el BPM doble/mitad respecto del otro, (2) centra la grilla
        sobre los bombos, (3) empareja tempo y compases (si los dos suenan). Siempre cuenta en pantalla qué encontró."""
        a, b = self.deck_a, self.deck_b
        cargados = [d for d in (a, b) if d.analysis and d.original_bpm]
        if not cargados:
            self._avisar_rejilla("⚠️ Cargá un tema y esperá a que termine el análisis")
            return
        for d in cargados:
            self._rej_visto[d.name] = (d.path, id(d.analysis))
        partes = []
        cambio = False                      # ¿se movió alguna grilla? (solo entonces hace falta volver a emparejar)
        for d in cargados:                  # 0) un BPM absurdo (fuera de 50-220) se lleva primero al rango musical
            if not d.playing and not d.analysis.get("usuario") and plegar_bpm(d.analysis):
                d.original_bpm = d.analysis["bpm"]; d._db_cache = None; d._update_bpm_label()
                try:
                    _guardar_cache(CACHE_DIR / (Path(d.path).stem + ".json"), d.analysis)
                except Exception:
                    pass
                cambio = True
                partes.append(f"Deck {d.name}: BPM fuera de rango → {d.analysis['bpm']:.1f}")
        # 1) octava
        if len(cargados) == 2:
            ba, bb = float(a.original_bpm), float(b.original_bpm)
            if max(ba, bb) / min(ba, bb) > 1.12:
                mejor = None
                for deck, bpm, otro_bpm in ((a, ba, bb), (b, bb, ba)):
                    if deck.playing:                       # al que está sonando no se le cambia el BPM (se oiría)
                        continue
                    for f in (0.5, 2.0):
                        r = max(bpm * f, otro_bpm) / min(bpm * f, otro_bpm)
                        clave = (round(r, 3), 0 if 70.0 <= bpm * f <= 180.0 else 1)
                        if mejor is None or clave < mejor[0]:
                            mejor = (clave, deck, f, r)
                if mejor and mejor[3] < 1.12 and mejor[3] < max(ba, bb) / min(ba, bb) * 0.8 and not mejor[1].analysis.get("usuario"):
                    _, deck, f, r = mejor
                    if deck.corregir_rejilla(factor=f, avisar=False):
                        cambio = True
                        partes.append(f"Deck {deck.name}: BPM {'×2' if f == 2.0 else '÷2'} → {deck.analysis['bpm']:.1f}")
        # 2) grilla centrada en los bombos
        for d in cargados:
            if d.analysis.get("usuario"):
                partes.append(f"Deck {d.name}: grilla corregida por vos, no se toca")
                continue
            if d.playing:                                     # a un tema que suena no se le mueve la grilla: se oiría un salto
                partes.append(f"Deck {d.name}: está sonando, grilla sin tocar")
                continue
            ms = d.centrar_rejilla(avisar=False)
            if ms:
                cambio = True
            if ms is None:
                partes.append(f"Deck {d.name}: bombos poco claros, grilla sin tocar")
            elif ms == 0.0:
                partes.append(f"Deck {d.name}: grilla ya centrada en los bombos")
            else:
                partes.append(f"Deck {d.name}: grilla corrida {ms:+.0f} ms sobre los bombos")
        if cambio:
            self.timeline.redraw()
        # 3) emparejar
        if len(cargados) == 2:
            ba, bb = float(a.original_bpm), float(b.original_bpm)
            if not self._bpm_compatibles():
                partes.append(f"BPM muy distintos ({ba:.0f} y {bb:.0f}): no se emparejan")
            elif a.playing and b.playing:
                entra = b if a.volume >= b.volume else a
                if self.magnet_on and not cambio:
                    partes.append("los dos suenan y ya están emparejados")        # nada que corregir: no se vuelve a saltar
                else:
                    entra.tempo_manual = False
                    self._auto_sync(entra)
                    self._alinear_ya(entra)
                    partes.append(f"Deck {entra.name} emparejado con {'A' if entra is b else 'B'} (tempo y compases)")
            else:
                partes.append("el emparejamiento se hace al darle play a los dos")
        else:
            partes.append("cargá el otro deck para emparejar")
        self._avisar_rejilla(" · ".join(partes))

    def _avisar_rejilla(self, msg):
        log("rejilla", "auto: " + msg)
        self._set_status("🎯 " + msg)
        self.lbl_rej.setText(msg)
