"""AutoMix — sincronización inteligente entre decks."""
import numpy as np
from setup.deck import Deck


# =====================================================================
# 5) SMART SYNC
# =====================================================================
class SmartSync:
    @staticmethod
    def _next_event_after(events, t_now, bpm):
        if not events:
            return t_now
        events = np.asarray(events)
        idx = np.searchsorted(events, t_now - 0.005)
        if idx < len(events):
            return float(events[idx])
        beat_dt = 60.0 / max(1e-6, bpm)
        last = events[-1]
        n = int(np.ceil((t_now - last) / beat_dt))
        return float(last + n * beat_dt)

    @staticmethod
    def compute_phase_error(master: Deck, slave: Deck, promedio=False, n_prom=6):
        if not (master.analysis and slave.analysis):
            return None

        rate_m = max(1e-6, master.rate_eff)
        rate_s = max(1e-6, slave.rate_eff)

        db_m = master.analysis.get("downbeats_full") or master.analysis.get("downbeats") or []
        db_s = slave.analysis.get("downbeats_full") or slave.analysis.get("downbeats") or []
        if not db_m or not db_s:
            return None

        t_m = master.position_seconds()
        t_s = slave.position_seconds()

        next_m = SmartSync._next_event_after(db_m, t_m, master.analysis["bpm"])
        next_s = SmartSync._next_event_after(db_s, t_s, slave.analysis["bpm"])

        falta_m = (next_m - t_m) / rate_m
        falta_s = (next_s - t_s) / rate_s
        err = falta_s - falta_m

        if promedio:
            arr_m = np.asarray(db_m, dtype=float)
            arr_s = np.asarray(db_s, dtype=float)
            i_m = int(np.searchsorted(arr_m, next_m - 1e-6))
            i_s = int(np.searchsorted(arr_s, next_s - 1e-6))
            n = int(min(n_prom, len(arr_m) - i_m, len(arr_s) - i_s))
            if n >= 2:
                f_m = (arr_m[i_m:i_m + n] - t_m) / rate_m
                f_s = (arr_s[i_s:i_s + n] - t_s) / rate_s
                err = float(np.mean(f_s - f_m))

        if len(db_s) >= 2:
            periodo = float(np.median(np.diff(np.asarray(db_s)))) / rate_s
        else:
            periodo = 4.0 * 60.0 / max(1e-6, slave.analysis["bpm"] * rate_s)
        if periodo > 0:
            err = ((err + periodo / 2.0) % periodo) - periodo / 2.0
        return err

    @staticmethod
    def _falta_suave(deck: Deck, n=12, pos=None):
        """Segundos REALES hasta el próximo downbeat y período real del compás, usando una grilla
        regular ajustada (regresión lineal ROBUSTA) sobre n downbeats vecinos: los downbeats mal
        detectados (compases de 2,26 s o 2,84 s en un tema de 2,62 s) se descartan en vez de arrastrar
        al entrante hacia adelante y hacia atrás."""
        if not deck.analysis:
            return None
        db = deck.analysis.get("downbeats_full") or deck.analysis.get("downbeats") or []
        arr = np.asarray(db, dtype=np.float64)
        if len(arr) < 3:
            return None
        t = (pos / deck.sr) if pos is not None else deck.position_seconds()
        rate = max(1e-6, deck.rate_eff)
        i = int(np.searchsorted(arr, t))
        lo = max(0, min(i - n // 2, len(arr) - n))
        seg = arr[lo:lo + n]
        if len(seg) < 3:
            return None
        k = np.arange(lo, lo + len(seg), dtype=np.float64)
        b, a = np.polyfit(k, seg, 1)             # t_k = a + b·k
        for tol in (0.08, 0.03):                 # 2 pasadas: se descartan los que se alejan de la recta
            ok = np.abs(seg - (a + b * k)) < tol
            if ok.sum() < max(4, len(seg) // 2):
                break
            b, a = np.polyfit(k[ok], seg[ok], 1)
        if not (b > 0.2):
            return None
        kn = np.ceil((t - a) / b - 1e-9)
        return float((a + b * kn - t) / rate), float(b / rate)

    @staticmethod
    def error_fase_suave(master: Deck, slave: Deck, pos_m=None, pos_s=None):
        """Cuánto va ATRASADO el entrante respecto de la grilla del que suena (s, positivo = atrasado),
        envuelto a ±medio compás. None si no se puede."""
        m = SmartSync._falta_suave(master, pos=pos_m)
        s = SmartSync._falta_suave(slave, pos=pos_s)
        if m is None or s is None:
            return None
        per = s[1]
        e = s[0] - m[0]
        return float(((e + per / 2.0) % per) - per / 2.0)

    @staticmethod
    def match_bpm(master: Deck, slave: Deck):
        bpm_m = master.analysis["bpm"] * master.tempo_rate
        bpm_s_orig = slave.analysis["bpm"]
        if bpm_s_orig <= 0:
            return False
        rate_slave = bpm_m / bpm_s_orig
        slave.set_tempo_from_fader(rate_slave)
        return True

    @staticmethod
    def align_downbeats(master: Deck, slave: Deck):
        err = SmartSync.error_fase_suave(master, slave)
        if err is None:
            err = SmartSync.compute_phase_error(master, slave)
        if err is None:
            return False, "No se pudo calcular la fase."

        SmartSync.saltar_fase(slave, err)
        return True, err

    @staticmethod
    def saltar_fase(slave: Deck, err):
        """Mueve el cursor del entrante `err` segundos (reales) de fase. Si eso lo mandaría antes del
        comienzo del tema (típico al arrancar desde 0:00), salta al siguiente compás en vez de quedarse
        clavado en 0 con el error sin corregir."""
        rate = slave.rate_eff
        delta = int(round(err * rate * slave.sr))
        fs = SmartSync._falta_suave(slave)
        per = int(round(fs[1] * rate * slave.sr)) if fs else 0
        with slave.lock:
            nuevo = slave.cursor + delta
            if nuevo < 0 and per > 0:
                nuevo += per * int(np.ceil(-nuevo / per))
            slave.cursor = int(np.clip(nuevo, 0, len(slave.audio) - 1))
            slave._cursor_frac = 0.0

    @staticmethod
    def preparar_entrada(master: Deck, slave: Deck):
        if not (master.analysis and slave.analysis):
            return False, "Ambos decks deben tener análisis."
        if master.audio is None or slave.audio is None:
            return False, "Ambos decks deben tener audio cargado."
        if master.analysis["bpm"] <= 0 or slave.analysis["bpm"] <= 0:
            return False, "BPM inválido."
        ok, err = SmartSync.align_downbeats(master, slave)
        if not ok:
            return False, err
        bpm_m = master.analysis["bpm"] * master.tempo_rate
        bpm_s_eff = slave.analysis["bpm"] * slave.tempo_rate
        return True, (f"BPM entrante {bpm_s_eff:.2f} = sonando {bpm_m:.2f} | fase alineada ({err*1000.0:+.1f} ms)")
