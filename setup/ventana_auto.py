"""AutoMix — mezcla automática: plan, siguiente tema, duración y disparo."""
import math
import os
import numpy as np
from PySide6.QtCore import QTimer
from setup.analisis import compat_armonica
from setup.base import _log_diferido, log
from setup.config import guardar_config, leer_config


class AutomaticoMixin:
    """Mezcla automática: plan, siguiente tema, duración y disparo (parte de la ventana principal)."""


    def _cargar_duracion_mezcla(self):
        try:
            return max(1, min(120, int(leer_config().get("mezcla_s", 10))))
        except Exception:
            return 10

    def _duracion_mezcla_cambio(self, v):
        log("config", f"duración de la mezcla: {v} s")
        self.btn_mix.setText(f"🎬 Mezclar ({v}s) [F2]")
        guardar_config(mezcla_s=int(v))

    # ================= RECETAS DE MEZCLA (según dónde hay voz/melodía) =================
    UMBRAL_VOZ = 0.45

    def _plan_activo(self):
        pl = getattr(self, "_plan", None)
        if pl and (self.mix_timer.isActive() or self.mix_pausa_timer.isActive()):
            return pl
        return None

    @staticmethod
    def _x_de_tiempo(T, dur):
        """Fracción de la mezcla (posición del crossfader) a los T segundos de empezar, contando la pausa de 3 s al 50 %."""
        mitad = dur / 2.0
        if T <= mitad:
            return T / dur
        if T <= mitad + 3.0:
            return 0.5
        return min(1.0, (T - 3.0) / dur)

    def _actividad(self, deck, dur_total):
        """Lista (cada 0,5 s reales desde ahora) de True/False: ¿hay voz/melodía en los medios de ese deck?"""
        an = deck.analysis or {}
        voz = an.get("voz") or []
        if not voz:
            return None
        dt = float(an.get("voz_dt", 0.5))
        pos = deck.position_virtual_seconds(); rate = max(1e-6, deck.rate_eff)
        out = []
        for i in range(int(dur_total / 0.5) + 1):
            k = int((pos + i * 0.5 * rate) / dt)
            out.append(bool(k < len(voz) and voz[k] >= self.UMBRAL_VOZ))
        return out

    def _planificar_mezcla(self, sale, entra, dur):
        """Elige la receta de esta mezcla mirando dónde hay voz/melodía en el tema que sale y en el que entra.
        Devuelve dict(pa, pb, ps, fa, nombre) o None (se usan los deslizadores del panel)."""
        W = dur + 3.0
        act_s, act_e = self._actividad(sale, W), self._actividad(entra, W)
        if act_s is None or act_e is None:
            return None
        n = len(act_s)
        def primer_silencio(a):                         # primer instante con 2 s sin actividad (0 = ya está sin actividad)
            for i in range(n):
                if not any(a[i:i + 4]):
                    return i * 0.5
            return None
        def primera_actividad(a):
            for i in range(n):
                if a[i]:
                    return i * 0.5
            return None
        fin_s = primer_silencio(act_s)                  # None = el que sale tiene voz durante toda la mezcla
        ini_e = primera_actividad(act_e)                # None = el que entra es instrumental durante toda la mezcla
        sale_activo = fin_s != 0.0
        entra_pronto = ini_e is not None and ini_e <= 0.3 * dur
        x = lambda T: self._x_de_tiempo(T, dur)
        pa, pb, ps, fa = self.punto_a, self.punto_b, self.punto_s, 1.0
        if not sale_activo:
            if ini_e is not None:
                nombre = "Voz nueva sobre la base vieja"
                pb, pa, ps = 0.0, 0.75, 0.8             # entra todo ya; el bajo viejo sigue casi hasta el final
            else:
                nombre = "Traspaso instrumental"
        elif entra_pronto:
            nombre = "Base nueva, voz vieja"
            ps = 0.15                                    # el bajo/bombo nuevo entra enseguida (en el compás)…
            pb = min(0.8, x(fin_s)) if fin_s is not None else 0.6   # …y su voz espera a que termine la del que sale
            pa, fa = max(0.2, pb - 0.2), min(1.0, pb + 0.1)
        else:
            nombre = "Entrada instrumental bajo la voz vieja"
            pb, ps, pa = 0.0, 0.3, 0.65                  # el nuevo entra completo; la voz vieja sigue un rato
        return {"pa": float(pa), "pb": float(pb), "ps": float(ps), "fa": float(fa), "nombre": nombre}

    def set_comp(self, v):
        log("config", f"compensar nivel: {'sí' if v else 'no'}")
        self.comp_nivel = bool(v)
        guardar_config(comp_nivel=self.comp_nivel)
        if hasattr(self, "mixer"):
            self.mixer.comp_activo = self.comp_nivel

    def set_recetas(self, v):
        log("config", f"recetas automáticas: {'sí' if v else 'no'}")
        self.recetas = bool(v)
        guardar_config(recetas=self.recetas)

    def set_forma_cruce(self, pa, pb, activo, ps=None, bandas=None):
        _log_diferido("forma", "config", f"forma de cruce: A {pa:.0%} · B {pb:.0%} · activa {'sí' if activo else 'no'}"
                      f"{'' if ps is None else f' · bajo {ps:.0%}'}{'' if bandas is None else f' · por bandas {chr(115)+chr(237) if bandas else chr(110)+chr(111)}'}")
        self.punto_a, self.punto_b, self.cruce_ab = float(pa), float(pb), bool(activo)
        if ps is not None:
            self.punto_s = float(ps)
        if bandas is not None:
            self.cruce_bandas = bool(bandas)
        guardar_config(punto_a=self.punto_a, punto_b=self.punto_b, cruce_ab=self.cruce_ab,
                       punto_s=self.punto_s, cruce_bandas=self.cruce_bandas)
        self._update_cf()

    def _auto_s_cambio(self, v):
        self.auto_s = int(v)
        guardar_config(auto_s=self.auto_s)

    def _programar_carga(self, detenido):
        if not self.carga_auto:
            return
        if self._carga_pendiente:
            return
        self._carga_pendiente = True
        def _run():
            self._carga_pendiente = False
            self._cargar_siguiente(detenido)
        QTimer.singleShot(400, _run)

    def _clave_de(self, deck):
        """Clave Camelot del tema cargado en un deck (de su análisis o del caché de la biblioteca)."""
        try:
            if deck is None or not deck.path:
                return None
            k = ((deck.analysis or {}).get("key") or {}).get("camelot")
            return k or self.biblioteca.info(deck.path)[1]
        except Exception:
            return None

    def _siguiente_armonico(self, path_actual):
        """Modo estricto: SOLO temas de clave compatible (misma, relativa o vecina) y BPM a ±8 %; el mejor primero,
        sin repetir los ya tocados. Devuelve (ruta, None) o (None, motivo)."""
        bib = self.biblioteca
        if not path_actual:
            return None, "no hay tema de referencia"
        if not hasattr(self, "_tocados"):
            self._tocados = set()
        ref = bib._clave(path_actual)
        self._tocados.add(ref)
        for d in (self.deck_a, self.deck_b):
            if d.path:
                self._tocados.add(bib._clave(d.path))
        bpm0, cam0, _, _ = bib.info(path_actual)
        if cam0 is None or not bpm0:
            return None, "el tema que suena no tiene clave analizada todavía"
        def candidatos():
            res = []
            for orden, r in enumerate(bib.todas()):
                if bib._clave(r) in self._tocados or not os.path.isfile(r):
                    continue
                bpm, cam, _, _ = bib.info(r)
                nivel = compat_armonica(cam0, cam)
                if not nivel or not bpm:                  # sin clave o que choca: no se considera
                    continue
                d = abs(bpm / bpm0 - 1.0)
                if d > 0.08:                              # tempo demasiado lejano para enganchar
                    continue
                res.append((nivel * 10.0 - d * 150.0 - orden * 1e-3, d, r))
            return res
        cands = candidatos()
        if not cands:                                  # ya se tocó todo lo compatible: se empieza otra vuelta
            self._tocados = {ref} | {bib._clave(d.path) for d in (self.deck_a, self.deck_b) if d.path}
            cands = candidatos()
        if not cands:
            return None, "ningún tema de la lista es compatible (clave y BPM) con el que suena"
        return max(cands, key=lambda c: c[0])[2], None

    def _siguiente_en_biblioteca(self, path_actual):
        if getattr(self, "chk_armonico", None) is not None and self.chk_armonico.isChecked():
            try:
                return self._siguiente_armonico(path_actual)      # estricto: si no hay compatible, no se carga ninguno
            except Exception:
                import traceback; traceback.print_exc()
        rutas = self.biblioteca.todas()
        clave = os.path.normcase(os.path.abspath(path_actual)) if path_actual else None
        for i, r in enumerate(rutas):
            if os.path.normcase(os.path.abspath(r)) == clave:
                for j in range(i + 1, len(rutas)):
                    if os.path.isfile(rutas[j]):
                        return rutas[j], None
                if rutas:
                    for j in range(len(rutas)):
                        if os.path.isfile(rutas[j]):
                            return rutas[j], None
                return None, "fin de la biblioteca"
        for r in rutas:
            if os.path.isfile(r):
                return r, None
        return None, "biblioteca vacía"

    def _cargar_siguiente(self, destino):
        if not self.carga_auto:
            return
        otro = self.deck_a if destino is self.deck_b else self.deck_b
        if not otro.path:          # el otro deck está vacío (p. ej. al iniciar): no cargar nada solo
            return
        referencia_path = otro.path
        ruta, motivo = self._siguiente_en_biblioteca(referencia_path)
        if ruta is None:
            self._set_status(f"🔁 Carga automática: {motivo}")
            return
        destino.load_track(ruta)
        k_sale, k_entra = self._clave_de(otro), self.biblioteca.info(ruta)[1]
        extra = f"  🎼 {k_sale}→{k_entra}" if (k_sale and k_entra) else ""
        self._set_status(f"🔁 Deck {destino.name} en espera: {os.path.basename(ruta)}{extra}")

    # ================= MEZCLA EN FRASE =================
    FRASE_COMPASES = 8

    def _db_de(self, deck):
        a = deck.analysis or {}
        db = a.get("downbeats_full") or a.get("downbeats") or []
        return np.asarray(db, dtype=np.float64)

    def _hasta_proxima_frase(self, sale):
        """Segundos reales hasta que el tema que suena empiece su próxima frase (cada 8 compases desde su primer
        compás). None si no hay grilla."""
        db = self._db_de(sale)
        if len(db) < self.FRASE_COMPASES + 1 or sale.audio is None:
            return None
        pos = sale.position_virtual_seconds()
        lim = db[::self.FRASE_COMPASES]
        sig = lim[lim > pos + 0.12]
        if not len(sig):
            return None
        return float((sig[0] - pos) / max(1e-6, sale.rate_eff))

    def _disparar_mezcla_auto(self, exacto=False):
        """Punto único de arranque de las mezclas automáticas (auto-enganche y carga automática).
        Con '🥁 En frase' espera al próximo comienzo de frase del tema que suena para arrancar justo ahí."""
        if getattr(self, "_frase_armada", False):
            return
        if self.mix_timer.isActive() or self.mix_pausa_timer.isActive():
            return
        f = self.crossfader.value()
        sale = self.deck_a if f <= 50 else self.deck_b
        entra = self.deck_b if sale is self.deck_a else self.deck_a
        if self.chk_armonico.isChecked():              # estricto: solo se engancha un tema compatible
            ks, ke = self._clave_de(sale), self._clave_de(entra)
            nivel = compat_armonica(ks, ke)
            try:
                bs = float((sale.analysis or {}).get("bpm", 0)) * sale.rate_eff
                be = float((entra.analysis or {}).get("bpm", 0)) * entra.tempo_rate
                lejos = bs > 0 and be > 0 and abs(be / bs - 1.0) > 0.08
            except Exception:
                lejos = False
            if not nivel or lejos:
                msg = (f"🎼 No se mezcla: {ks or '?'} → {ke or '?'} no es compatible" if not nivel
                       else "🎼 No se mezcla: el BPM del tema en espera está demasiado lejos")
                if getattr(self, "_aviso_armonico", None) != msg:
                    self._aviso_armonico = msg
                    print("[mezcla]", msg)
                    self._set_status(msg)
                return
            self._aviso_armonico = None
        espera = None
        if self.chk_frases.isChecked() and not exacto and not self._cruce_simple() and sale.playing and sale.analysis and entra.analysis and entra.audio is not None:
            espera = self._hasta_proxima_frase(sale)
            if espera is not None:
                dur = self._duracion_mezcla_para(sale, entra, True)
                resta = (len(sale.audio) - sale.cursor - sale.loop_desfase) / (sale.sr * max(1e-6, sale.rate_eff))
                if espera + dur + 4.0 > resta:        # esperar a la frase no deja tiempo: se mezcla ya
                    espera = None
        if espera is None or espera < 0.05:
            if not entra.playing and entra.audio is not None and entra.analysis and not entra.pos_manual:
                db_e = self._db_de(entra)
                if len(db_e):
                    entra.set_position_seconds(float(db_e[0]))      # el entrante sale desde su primer compás
            self._mix_auto = True
            self._mix_clicked()
            return
        self._frase_armada = True
        pa, pb = self.deck_a.path, self.deck_b.path
        self._set_status(f"🥁 Mezcla armada: arranca en la próxima frase ({espera:.1f} s)")
        def _go():
            self._frase_armada = False
            if (self.deck_a.path, self.deck_b.path) != (pa, pb) or self.mix_timer.isActive() or self.mix_pausa_timer.isActive():
                return                                  # cambió algo mientras esperaba (mezcla manual, otro tema…)
            if not entra.playing and entra.audio is not None and entra.analysis and not entra.pos_manual:
                db_e = self._db_de(entra)
                if len(db_e):
                    entra.set_position_seconds(float(db_e[0]))      # el entrante sale desde su primer compás
            self._mix_auto = True
            self._mix_clicked()
        QTimer.singleShot(int(max(0.0, espera - 0.02) * 1000), _go)

    def _duracion_mezcla_para(self, sale, entra, auto):
        """Duración de la mezcla: la elegida por el usuario. En las automáticas se ajusta a compases enteros y,
        si las tonalidades chocan o los BPM son muy distintos, se acorta para pasar rápido de un tema al otro."""
        dur = float(self.spin_mix.value())
        if not auto:
            return dur
        try:
            bpm = float((sale.analysis or {}).get("bpm", 0)) * sale.rate_eff
            comp = compat_armonica(self._clave_de(sale), self._clave_de(entra)) if self.chk_armonico.isChecked() else None
            bpm_e = float((entra.analysis or {}).get("bpm", 0)) * entra.tempo_rate
            dif = abs(bpm_e / bpm - 1.0) if bpm > 0 and bpm_e > 0 else 0.0
            if bpm > 0 and self.chk_frases.isChecked():
                compas = 4.0 * 60.0 / bpm
                n = min((2, 4, 8, 16), key=lambda c: abs(math.log2(c) - math.log2(max(0.5, dur / compas))))   # compases de verdad: 2, 4, 8 o 16
                if comp == 0 or dif > 0.08:
                    n = 2                             # choque de tonalidad o de tempo: corte rápido, 2 compases
                dur = n * compas
            elif comp == 0 or dif > 0.08:
                dur = min(dur, 4.0)
        except Exception:
            pass
        return max(1.0, dur)

    def _auto_vigilar(self):
        if not self.carga_auto or self.mix_timer.isActive() or self.mix_pausa_timer.isActive():
            return
        f = self.crossfader.value()
        if f not in (0, 100):
            return
        sonando = self.deck_a if f == 0 else self.deck_b
        espera = self.deck_b if f == 0 else self.deck_a
        if not sonando.playing or sonando.audio is None or espera.playing:
            return
        if espera.audio is None or not espera.analysis:
            return
        resta = (len(sonando.audio) - sonando.cursor - sonando.loop_desfase) / (sonando.sr * max(1e-6, sonando.rate_eff))
        if resta <= max(float(self.auto_s), self.spin_mix.value() + 4.0):   # +3 s de pausa al 50 % +1 s de margen
            self._set_status(f"🔁 Mezcla automática hacia el Deck {espera.name}")
            self._disparar_mezcla_auto()
