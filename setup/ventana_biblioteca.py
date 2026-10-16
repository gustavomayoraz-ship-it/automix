"""AutoMix — biblioteca: análisis de los temas, orden, carga en los decks."""
import os
from PySide6.QtWidgets import QAbstractItemView, QApplication
from PySide6.QtCore import QTimer, Qt
from setup.ajustes import SUPPORTED
from setup.analisis import _mantener_vivo
from setup.base import log
from setup.config import guardar_config, leer_config
from setup.deck import Deck
from setup.hilos_analisis import AnalizadorBiblioteca


class BibliotecaMixin:
    """Biblioteca: análisis de los temas, orden, carga en los decks (parte de la ventana principal)."""


    _analizador_bib = None
    _fallidos = None
    _ordenar_al_terminar = False

    def _analisis_en_curso(self):
        return self._analizador_bib is not None and self._analizador_bib.isRunning()

    def _iniciar_analisis(self, rutas, forzar, fin, texto):
        self.biblioteca.marcar(rutas)
        a = AnalizadorBiblioteca(rutas, forzar=forzar)
        _mantener_vivo(a)
        a.progreso.connect(lambda i, t: self._set_status(f"{texto}: {i}/{t}"))
        a.tema_listo.connect(self.biblioteca.quitar_de_cola)
        a.tema_listo.connect(lambda _r: self._reordenar_pronto())          # la lista se va ordenando a medida que se analiza
        a.terminado.connect(fin)
        self._analizador_bib = a
        a.start()

    def _pendientes(self):
        if self._fallidos is None:
            self._fallidos = set()
        return [r for r in self.biblioteca.temas_sin_analisis()
                if self.biblioteca._clave(r) not in self._fallidos and os.path.isfile(r)]

    def _auto_analizar(self):
        """Los temas nuevos de la lista se analizan solos (se ven con ⏳ hasta que terminan)."""
        if self._analisis_en_curso():
            return
        faltan = self._pendientes()
        if not faltan:
            self._ordenar_al_terminar = False
            return
        self._set_status(f"⏳ Analizando {len(faltan)} temas (BPM)…")
        self._iniciar_analisis(faltan, False, self._fin_analisis, "⏳ Analizando BPM")

    def _fin_analisis(self):
        self.biblioteca.marcar(())
        if self._fallidos is None:
            self._fallidos = set()
        for r in self.biblioteca.temas_sin_analisis():       # los que no se pudieron analizar no se reintentan en bucle
            self._fallidos.add(self.biblioteca._clave(r))
        if self._ordenar_al_terminar:
            self._ordenar_al_terminar = False
            self._ordenar_lista()
            self._set_status("✅ Biblioteca ordenada")
        else:
            self._set_status("✅ Lista analizada")
        QTimer.singleShot(300, self._auto_analizar)           # por si se agregaron temas mientras tanto

    def _ordenar_lista(self):
        """Con 🎼 Armónico y/o 🥁 En frase la lista se ordena como cadena de mezcla (empezando por el tema que
        suena); sin ninguna, por BPM de menor a mayor."""
        arm, fra = self.chk_armonico.isChecked(), self.chk_frases.isChecked()
        if getattr(self, "_orden_tono", False):
            self.biblioteca.ordenar_por_tono()
            return
        if not (arm or fra):
            self.biblioteca.ordenar_por_bpm()
            return
        prim = self._deck_primario()
        inicio = prim.path if (prim is not None and prim.path) else None
        self.biblioteca.ordenar_inteligente(arm, fra, inicio)

    def _reordenar_pronto(self, ms=600):
        """Reordena la lista (con retardo, para agrupar varios cambios) a medida que se analizan los temas."""
        t = getattr(self, "_t_reordenar", None)
        if t is None:
            t = self._t_reordenar = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._reordenar_ahora)
        t.start(ms)

    def _reordenar_ahora(self):
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:     # no mover la lista mientras se arrastra un tema
            self._reordenar_pronto(500)
            return
        try:
            self._ordenar_lista()
        except Exception:
            import traceback; traceback.print_exc()

    def _alternar_agrupada(self, v):
        self.biblioteca.set_agrupado(bool(v))
        if v:
            self._ordenar_lista()                             # dentro de cada carpeta, el orden de siempre (BPM o tono)
        guardar_config(lib_agrupada=bool(v))
        self._set_status("📂 Lista separada por carpetas (clic en un título para cerrarlo o abrirlo)" if v else "📃 Lista plana")

    def _ordenar_biblioteca_tono(self):
        self._orden_tono = True                               # se mantiene mientras se analiza y suenan los temas
        self.biblioteca.ordenar_por_tono()
        faltan = [r for r in self._pendientes()]
        self._set_status("🎼 Biblioteca ordenada por tono" + (f" — analizando {len(faltan)} temas sin tono…" if faltan else ""))
        if faltan and not self._analisis_en_curso():
            self._ordenar_al_terminar = True
            self._iniciar_analisis(faltan, False, self._fin_analisis, "⏳ Analizando tono")

    def _ordenar_biblioteca_bpm(self):
        self._orden_tono = False
        self._ordenar_lista()                                 # ya: primero los que tienen BPM conocido
        self._fallidos = set()                                # un clic explícito vuelve a intentar los que fallaron
        faltan = self._pendientes()
        if not faltan:
            self._set_status("✅ Biblioteca ordenada por BPM")
            return
        self._ordenar_al_terminar = True
        if self._analisis_en_curso():
            self._set_status("⏳ Analizando la lista… se ordena sola al terminar")
            return
        self._set_status(f"⏳ Analizando {len(faltan)} temas (BPM)…")
        self._iniciar_analisis(faltan, False, self._fin_analisis, "⏳ Analizando BPM")

    def _reanalizar_biblioteca(self):
        if self._analizador_bib is not None and self._analizador_bib.isRunning():
            if self._analizador_bib.forzar:                       # segundo clic = cancelar
                self._analizador_bib.cancelar = True
                self._set_status("⏹ Cancelando re-análisis…")
            else:
                self._set_status("⏳ Analizando biblioteca…")
            return
        rutas = self.biblioteca.todas()
        if not rutas:
            self._set_status("La lista está vacía")
            return
        self._set_status(f"🔄 Re-analizando {len(rutas)} temas… (clic otra vez en el botón para cancelar)")
        self.btn_reanalizar.setText("⏹ Cancelar")
        self._iniciar_analisis(rutas, True, self._fin_reanalisis, "🔄 Re-analizando BPM")

    def _fin_reanalisis(self):
        self.biblioteca.marcar(())
        cancelado = bool(self._analizador_bib and self._analizador_bib.cancelar)
        self.btn_reanalizar.setText("🔄 Re-analizar")
        self._set_status("⏹ Re-análisis cancelado" if cancelado else
                         "✅ Lista re-analizada. Si un tema ya estaba cargado en un deck, volvé a cargarlo para usar el BPM nuevo")

    def _filtrar_biblioteca(self, txt):
        t = txt.strip().lower()
        for i in range(self.biblioteca.count()):
            it = self.biblioteca.item(i)
            if self.biblioteca._es_cab(it):
                continue
            it.setHidden(bool(t) and t not in it.text().lower())

    def _biblioteca_cambio(self):
        self.lbl_lib.setText(f"📁 Biblioteca ({len(self.biblioteca.todas())})")
        self.biblioteca.guardar()
        if self.biblioteca.count() == 0:
            self._vaciar_decks()

    def _vaciar_decks(self):
        """La lista quedó vacía: los dos reproductores y la línea de tiempo (el espectro de abajo) se limpian."""
        a, b = self.deck_a, self.deck_b
        if a.audio is None and b.audio is None and not a.path and not b.path:
            return
        log("programa", "lista vacía: se descargan los dos decks")
        self.mix_timer.stop(); self.mix_pausa_timer.stop()
        self._plan = None
        self._frase_armada = False
        self._mix_esperando = False
        self._mix_auto = False
        self._target_rate_a = self._target_rate_b = None
        try:
            self._soltar_sync(None)
        except Exception:
            pass
        self.magnet_on = False
        a.descargar(); b.descargar()
        try:
            self.timeline.redraw()
        except Exception:
            import traceback; traceback.print_exc()
        self.biblioteca.pintar(None, None)
        self._set_status("🗑️ Lista vacía: reproductores descargados")

    def _restaurar_decks(self):
        """Al abrir: vuelven a quedar cargados los temas que tenían los decks al cerrar (si siguen existiendo y la lista no está vacía)."""
        if self.biblioteca.count() == 0:
            return
        cfg = leer_config().get("decks_cargados") or {}
        for d in (self.deck_a, self.deck_b):
            p = cfg.get(d.name)
            if p and os.path.isfile(p) and p.lower().endswith(SUPPORTED) and not d.path:
                log("programa", f"se recupera el Deck {d.name}: {os.path.basename(p)}")
                d.load_track(p)

    def _ubicar_en_lista(self, path):
        """Clic en el nombre del tema de un deck: lo busca en la biblioteca, lo selecciona y lo deja a la vista."""
        if not path:
            self._set_status("No hay ningún tema cargado en ese deck")
            return
        bib = self.biblioteca
        clave = bib._clave(path)
        for i in range(bib.count()):
            it = bib.item(i)
            if bib._es_cab(it):
                continue
            if bib._clave(it.data(Qt.ItemDataRole.UserRole)) == clave:
                if it.isHidden():                       # el filtro de búsqueda (o una carpeta cerrada) lo estaba ocultando
                    self.ed_filtro.clear()
                    if bib.agrupado:
                        bib._plegadas.discard(bib._carpeta(path)); bib._quitar_cab(); bib._poner_cab()
                        for j in range(bib.count()):
                            if not bib._es_cab(bib.item(j)) and bib._clave(bib.item(j).data(Qt.ItemDataRole.UserRole)) == clave:
                                it = bib.item(j); break
                bib.clearSelection()
                bib.setCurrentItem(it)
                it.setSelected(True)
                bib.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
                self._set_status(f"📍 Ubicado en la lista: {os.path.basename(path)}")
                return
        self._set_status("Ese tema no está en la biblioteca")

    def _biblioteca_doble_clic(self, it):
        if self.biblioteca._es_cab(it):
            return
        p = it.data(Qt.ItemDataRole.UserRole)
        if not os.path.isfile(p): return
        a, b = self.deck_a, self.deck_b
        if a.playing and b.playing:
            self._set_status("Los dos decks están sonando.")
            return
        if not a.playing and not b.playing:
            # no suena nada: el tema elegido va al deck A y el que le sigue (según la lista / el modo armónico) al B
            a.load_track(p)
            try:
                ruta, motivo = self._siguiente_en_biblioteca(p)
            except Exception:
                import traceback; traceback.print_exc()
                ruta, motivo = None, "no se pudo elegir el siguiente"
            if ruta is not None and os.path.normcase(os.path.abspath(ruta)) != os.path.normcase(os.path.abspath(p)):
                b.load_track(ruta)
                k0, k1 = self._clave_de(a), self.biblioteca.info(ruta)[1]
                extra = f"  🎼 {k0}→{k1}" if (k0 and k1) else ""
                self._set_status(f"▶ Deck A: {os.path.basename(p)} · Deck B en espera: {os.path.basename(ruta)}{extra}")
            else:
                self._set_status(f"▶ Deck A: {os.path.basename(p)} · Deck B: {motivo or 'sin tema siguiente'}")
            return
        (b if a.playing else a).load_track(p)      # suena uno: el elegido va al deck que está en espera

    def _on_analysis(self, deck, res):
        self.timeline.redraw()
        try:
            self._apply_shared_bpm(self.crossfader.value() / 100.0)
        except Exception:
            import traceback; traceback.print_exc()
        try:                                  # el análisis llegó con el tema ya sonando: se empareja ahora mismo
            d = deck if isinstance(deck, Deck) else (self.deck_a if deck == "A" else self.deck_b)   # llega el nombre ("A"/"B")
            otro = self.deck_b if d is self.deck_a else self.deck_a
            if d.playing and otro.playing and not self.magnet_on and d.analysis and otro.analysis:
                self._auto_sync(d)
                self._alinear_ya(d)
        except Exception:
            import traceback; traceback.print_exc()
