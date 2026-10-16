"""AutoMix — crossfader, tempo compartido y sincronía entre decks."""
import math
import time
import numpy as np
from setup.ajustes import CF_BAJA_DESDE
from setup.base import _log_diferido
from setup.config import perfil_cruce_ab, perfil_cruce_bandas
from setup.sync import SmartSync


class SyncMixin:
    """Crossfader, tempo compartido y sincronía entre decks (parte de la ventana principal)."""


    def _smooth_tempo(self):
        ep = self.__dict__.setdefault("_aj_ep", {})
        for attr_t, attr_al, deck in (("_target_rate_a", "_alpha_a", self.deck_a),
                                      ("_target_rate_b", "_alpha_b", self.deck_b)):
            target = getattr(self, attr_t)
            if target is None:
                self._fin_ajuste(deck, False) if id(deck) in ep else None
                continue
            if deck.tempo_manual:
                setattr(self, attr_t, None); self._fin_ajuste(deck, False); continue
            if self.magnet_on and deck is self.slave_for_magnet:      # lo maneja el sync, sin retraso
                setattr(self, attr_t, None); self._fin_ajuste(deck, False); continue
            alpha = getattr(self, attr_al)
            cur = deck.tempo_rate
            new = cur + (target - cur) * alpha
            llego = abs(target - new) < 1e-5
            if llego:
                new = target
                setattr(self, attr_t, None)
                setattr(self, attr_al, 0.05)
            if new != cur:
                deck.tempo_rate = new
                deck._update_bpm_label()
                if deck.playing:                              # el reloj marca cuánto falta para llegar a la velocidad del enganche
                    r0 = ep.setdefault(id(deck), cur)
                    dist0 = abs(target - r0)
                    if dist0 >= 0.004:
                        deck.mostrar_ajuste(1.0 - min(1.0, abs(target - new) / dist0))
            if llego:
                self._fin_ajuste(deck, True)

    def _update_cf(self):
        fader_val = self.crossfader.value()
        fader_cambio = (self._fader_prev != fader_val)
        if fader_cambio and not (self.mix_timer.isActive() or self.mix_pausa_timer.isActive()):
            _log_diferido("cf", "crossfader", f"{fader_val} % (0 = A · 100 = B)")      # en las mezclas automáticas no: ya lo cuenta [mezcla]
        self._fader_prev = fader_val

        x = fader_val / 100.0

        if fader_val == 0: self._cf_dir = "AB"
        elif fader_val == 100: self._cf_dir = "BA"

        simple = self._cruce_simple()
        bandas = bool(self.cruce_ab and self.cruce_bandas and not simple)
        if simple:                                       # BPM muy distintos: cruce simple de potencia constante
            gan_a = math.cos(x * math.pi / 2.0)
            gan_b = math.sin(x * math.pi / 2.0)
            hi_a = lo_a = gan_a
            hi_b = lo_b = gan_b
        elif bandas:
            t = x if self._cf_dir == "AB" else 1.0 - x
            pl = self._plan_activo()
            if pl:
                vs_h, ve_h, vs_l, ve_l = perfil_cruce_bandas(t, pl["pa"], pl["pb"], pl["ps"], fin_a=pl["fa"])
            else:
                vs_h, ve_h, vs_l, ve_l = perfil_cruce_bandas(t, self.punto_a, self.punto_b, self.punto_s)
            if self._cf_dir == "AB":
                hi_a, hi_b, lo_a, lo_b = vs_h, ve_h, vs_l, ve_l
            else:
                hi_a, hi_b, lo_a, lo_b = ve_h, vs_h, ve_l, vs_l
        else:
            if self.cruce_ab:
                t = x if self._cf_dir == "AB" else 1.0 - x
                v_sale, v_entra = perfil_cruce_ab(t, self.punto_a, self.punto_b)
                gan_a, gan_b = (v_sale, v_entra) if self._cf_dir == "AB" else (v_entra, v_sale)
            else:
                tramo = max(1e-6, 1.0 - CF_BAJA_DESDE)
                gan_a = min(1.0, max(0.0, (1.0 - x) / tramo))
                gan_b = min(1.0, max(0.0, x / tramo))
            hi_a = lo_a = gan_a
            hi_b = lo_b = gan_b

        self.deck_a.vol_hi, self.deck_a.vol_lo = hi_a, lo_a
        self.deck_b.vol_hi, self.deck_b.vol_lo = hi_b, lo_b
        self.deck_a.volume = max(hi_a, lo_a)
        self.deck_b.volume = max(hi_b, lo_b)
        self.mixer.banda_activa = bandas

        self._apply_shared_bpm(x)

        if fader_val == 0 and self.deck_a.original_bpm:
            self._target_rate_a = 1.0
            self._alpha_a = 0.05
        elif fader_val == 100 and self.deck_b.original_bpm:
            self._target_rate_b = 1.0
            self._alpha_b = 0.05

        if not fader_cambio:
            return

        if fader_val == 0:
            if self.deck_b.playing:
                self.deck_b.stop()
                self._set_status("🛑 Deck B detenido")
            self._programar_carga(self.deck_b)
        elif fader_val == 100:
            if self.deck_a.playing:
                self.deck_a.stop()
                self._set_status("🛑 Deck A detenido")
            self._programar_carga(self.deck_a)

    BPM_RATIO_MAX = 1.22      # más distancia que esta entre los dos temas: no se estiran (sonarían acelerados/graves)

    def _bpm_compatibles(self):
        a, b = self.deck_a.original_bpm, self.deck_b.original_bpm
        if not (a and b):
            return True
        return max(a, b) / min(a, b) <= self.BPM_RATIO_MAX

    def _cruce_simple(self):
        """True si los dos temas tienen BPM muy distintos: no se empareja nada (ni tempo, ni compases, ni fase)
        y la mezcla es un cruce simple de volumen, sin bandas ni recetas."""
        return not self._bpm_compatibles()

    def _apply_shared_bpm(self, x):
        bpm_a0 = self.deck_a.original_bpm
        bpm_b0 = self.deck_b.original_bpm
        if not (bpm_a0 and bpm_b0):
            return
        if not self._bpm_compatibles():
            self._target_rate_a = self._target_rate_b = 1.0       # cada tema a su velocidad natural
            self._alpha_a = self._alpha_b = 0.05
            return

        target_bpm_a = bpm_a0 + (bpm_b0 - bpm_a0) * x
        target_bpm_b = bpm_a0 + (bpm_b0 - bpm_a0) * x

        self._target_rate_a = float(np.clip(target_bpm_a / bpm_a0, 0.5, 2.0))
        self._target_rate_b = float(np.clip(target_bpm_b / bpm_b0, 0.5, 2.0))
        self._alpha_a = self._alpha_b = 0.05

    def _auto_sync(self, deck):
        otro = self.deck_b if deck is self.deck_a else self.deck_a
        if not otro.playing:
            if self.magnet_on and self.master_for_magnet is deck:
                self._soltar_sync(None)
            return
        master, slave = otro, deck
        if not (master.original_bpm and slave.original_bpm):
            return
        if slave.tempo_manual:                       # tempo fijado a mano: se respeta (se suelta al mezclar o con Reset)
            if self.magnet_on:
                self._soltar_sync(None)
            return
        slave.trim = 1.0
        self._err_filtrado = 0.0
        self._sync_I = 0.0; self._sync_t = None; self._sync_hist = []
        if not self._bpm_compatibles():
            slave.set_tempo_from_fader(1.0)
            self._target_rate_a = self._target_rate_b = None
            if self.magnet_on:
                self._soltar_sync(None)
            # BPM muy distintos: NO se alinean compases (eso hacía saltar al entrante hacia atrás y adelante)
            msg = (f"↔ BPM muy distintos ({master.original_bpm:.0f} y {slave.original_bpm:.0f}): "
                   f"cruce simple, cada tema mantiene su velocidad")
            if getattr(self, "_aviso_simple", None) != msg:
                self._aviso_simple = msg
                print("[mezcla]", msg)
            self._set_status(msg)
            return
        bpm_maestro = master.original_bpm * master.rate_eff
        rate_slave = float(np.clip(bpm_maestro / slave.original_bpm, 0.5, 2.0))
        r_ini = slave.tempo_rate
        slave.set_tempo_from_fader(rate_slave)
        self._target_rate_a = self._target_rate_b = None
        if abs(rate_slave - r_ini) >= 0.004:
            slave.barrido_ajuste()                   # el entrante ajustó su velocidad al que suena: lo marca el relojito

        ok, msg = SmartSync.preparar_entrada(master, slave)
        self.timeline.redraw()
        self._set_status(("🔗 " if ok else "⚠️ ") + f"{slave.name}→{master.name}: " + msg)
        if ok:
            self.master_for_magnet = master
            self.slave_for_magnet = slave
            self.magnet_on = True
            if not self.magnet_timer.isActive():
                self.magnet_timer.start(25)
            slave_playing_antes = slave.playing
            slave.playing = True
            try:
                self._apply_shared_bpm(self.crossfader.value() / 100.0)
            finally:
                slave.playing = slave_playing_antes

    # Control de fase PI: el entrante SIGUE exactamente el tempo del que suena (sin retraso) y solo
    # se le suma un microajuste de velocidad para cerrar el error de fase. NUNCA salta mientras se oye.
    SYNC_KP = 1.0               # (1/s)
    SYNC_KI = 0.20              # (1/s²)
    SYNC_TRIM_MAX = 0.025
    SYNC_SLEW = 0.0006          # cambio máximo del microajuste por tick de 25 ms
    SYNC_SALTO_S = 0.012        # salto de fase solo si el entrante está en silencio y el error supera esto
    SYNC_VOL_SILENCIO = 0.02

    def _magnet_correct(self):
        if not self.magnet_on: return
        master = self.master_for_magnet
        slave = self.slave_for_magnet
        if master is None or slave is None: return
        if not master.playing:
            self._soltar_sync(slave); return
        if not slave.playing:
            slave.trim = 1.0
            self._soltar_sync(master); return

        ahora = time.monotonic()
        dt = 0.025 if self._sync_t is None else float(np.clip(ahora - self._sync_t, 0.005, 0.1))
        self._sync_t = ahora

        # 1) velocidad base: exactamente el BPM del que suena (si él se mueve, el entrante lo acompaña al instante)
        if master.original_bpm and slave.original_bpm and self._bpm_compatibles():
            base = float(np.clip(master.original_bpm * master.rate_eff / slave.original_bpm, 0.5, 2.0))
            slave.tempo_rate = base
            self._sync_n += 1
            if self._sync_n % 8 == 0:
                slave.set_tempo_from_fader(base)            # refresca slider y etiqueta
        else:
            return

        # 2) error de fase (mediana de los últimos 5: descarta el pico de 1 bloque de audio entre los dos decks)
        snap = self.mixer.snap_pos            # posiciones de ambos decks en el mismo instante (sin picos de 1 bloque)
        if snap is not None:
            pm, ps = (snap[0], snap[1]) if master is self.deck_a else (snap[1], snap[0])
        else:
            pm = ps = None
        e_raw = SmartSync.error_fase_suave(master, slave, pm, ps)
        if e_raw is None: return
        self._sync_hist.append(e_raw)
        if len(self._sync_hist) > 5:
            self._sync_hist.pop(0)
        e = float(np.median(self._sync_hist))

        # 3) en silencio se puede saltar sin que se note; sonando, jamás
        if slave.volume < self.SYNC_VOL_SILENCIO and abs(e) > self.SYNC_SALTO_S and len(self._sync_hist) >= 5:
            SmartSync.saltar_fase(slave, e)
            slave.trim = 1.0
            self._sync_I = 0.0
            self._sync_hist = []
            return

        # 4) PI sobre la velocidad (siempre hacia adelante, cambios suaves)
        self._sync_I = float(np.clip(self._sync_I + self.SYNC_KI * e * dt, -0.01, 0.01))
        objetivo = 1.0 + float(np.clip(self.SYNC_KP * e + self._sync_I, -self.SYNC_TRIM_MAX, self.SYNC_TRIM_MAX))
        slave.trim += float(np.clip(objetivo - slave.trim, -self.SYNC_SLEW, self.SYNC_SLEW))
        self._err_filtrado = e
        if self._sync_n % 80 == 0:
            print(f"[sync] {slave.name}→{master.name} error {e*1000:+.1f} ms | trim {slave.trim:.4f} | I {self._sync_I:+.4f} | vol {slave.volume:.2f}")

    def _vigilar_sync(self):
        """Red de seguridad: si suenan los dos decks, hay grilla en ambos y el sync no está activo, se empareja."""
        a, b = self.deck_a, self.deck_b
        if self.magnet_on or not (a.playing and b.playing and a.analysis and b.analysis):
            return
        if self._cruce_simple():                       # BPM muy distintos: no hay nada que emparejar
            return
        if (a.tempo_manual or b.tempo_manual) and not (self.mix_timer.isActive() or self.mix_pausa_timer.isActive()):
            return                                     # tempo fijado a mano: se respeta hasta que mezcle o toque Reset
        t = time.monotonic()
        if t - getattr(self, "_t_vig_sync", 0.0) < 1.5:
            return
        self._t_vig_sync = t
        if self.mix_timer.isActive() or self.mix_pausa_timer.isActive():
            entra = b if self.mix_to == 100 else a
        else:
            entra = b if a.volume >= b.volume else a
        print(f"[sync] el sync no estaba activo con los dos decks sonando: se empareja el Deck {entra.name}")
        self._auto_sync(entra)
        self._alinear_ya(entra)

    def _alinear_ya(self, entra):
        """Salto de fase inmediato del entrante contra el que suena (primer downbeat), sin esperar al PI.
        Así la mezcla arranca con error ~0 y el ajuste fino solo mantiene."""
        sale = self.deck_a if entra is self.deck_b else self.deck_b
        if not (sale.playing and entra.playing and sale.analysis and entra.analysis):
            return
        if not self._bpm_compatibles():
            return
        snap = None
        ok, err = SmartSync.align_downbeats(sale, entra)
        if ok:
            entra.trim = 1.0
            self._sync_I = 0.0; self._sync_hist = []; self._sync_t = None
            self.master_for_magnet, self.slave_for_magnet = sale, entra
            self.magnet_on = True
            if not self.magnet_timer.isActive():
                self.magnet_timer.start(25)

    def _soltar_sync(self, quedo):
        self.magnet_on = False
        self.magnet_timer.stop()
        if quedo is None: return
        quedo.tempo_rate = float(np.clip(quedo.tempo_rate * quedo.trim, 0.5, 2.0))   # mismo rate_eff: sin escalón
        quedo.trim = 1.0
        if quedo.tempo_manual:
            return
        if quedo.playing and abs(quedo.tempo_rate - 1.0) > 1e-4:
            if quedo is self.deck_a:
                self._target_rate_a, self._alpha_a = 1.0, 0.01
            else:
                self._target_rate_b, self._alpha_b = 1.0, 0.01
            self._set_status("🔗 Sync suelto: velocidad normal")
