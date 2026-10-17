"""AutoMix — lista de temas (biblioteca)."""
from pathlib import Path
import json
import os
import re
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem, QStyledItemDelegate
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem
from PySide6.QtCore import QMimeData, QUrl, Qt, Signal
from setup.ajustes import FUENTE_BOOST, SUPPORTED
from setup.analisis import compat_armonica
from setup.base import CACHE_DIR, log
from setup.tema import COLOR_DECK_A, COLOR_DECK_B, TEMA


# =====================================================================
# 3.7) BIBLIOTECA
# =====================================================================
BIBLIOTECA_JSON = CACHE_DIR / "biblioteca.json"


def _escanear(rutas):
    out = []
    for p in rutas:
        if os.path.isdir(p):
            for raiz, dirs, archivos in os.walk(p):
                dirs.sort(key=str.lower)
                for f in sorted(archivos, key=str.lower):
                    if f.lower().endswith(SUPPORTED):
                        out.append(os.path.join(raiz, f))
        elif os.path.isfile(p) and p.lower().endswith(SUPPORTED):
            out.append(p)
    return out


class _DelegadoFondo(QStyledItemDelegate):
    """Pinta el fondo (BackgroundRole) del item: la hoja de estilos lo ignora."""
    def paint(self, painter, option, index):
        br = index.data(Qt.ItemDataRole.BackgroundRole)
        if br is not None and br != QBrush():
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(br)
            painter.drawRoundedRect(option.rect.adjusted(1, 1, -1, -1), 5, 5)
            painter.restore()
        der = index.data(Qt.ItemDataRole.UserRole + 3)           # texto a la derecha (duración; en los títulos "cantidad / duración total")
        if der:
            opt = QStyleOptionViewItem(option)
            fm = QFontMetrics(opt.font)
            w = fm.horizontalAdvance(der) + 12
            opt.rect.setRight(opt.rect.right() - w)
            super().paint(painter, opt, index)
            painter.save()
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            painter.setPen(fg.color() if fg is not None and fg != QBrush() else option.palette.text().color())
            painter.setFont(opt.font)
            painter.drawText(option.rect.adjusted(0, 0, -8, 0), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), der)
            painter.restore()
            return
        super().paint(painter, option, index)          # (antes decía `opt`, que solo existe si hay texto a la derecha: sin duración fallaba y la lista no se dibujaba)


def _reagrupa(f):
    """Los ordenamientos trabajan solo con temas: se sacan los encabezados de carpeta antes y se vuelven a poner después."""
    def w(self, *a, **k):
        if not self.agrupado:
            return f(self, *a, **k)
        sel = {self._clave(it.data(Qt.ItemDataRole.UserRole)) for it in self.selectedItems() if not self._es_cab(it)}
        barra = self.verticalScrollBar().value()
        self._quitar_cab()
        try:
            return f(self, *a, **k)
        finally:
            self._poner_cab()
            for i in range(self.count()):
                it = self.item(i)
                if not self._es_cab(it) and self._clave(it.data(Qt.ItemDataRole.UserRole)) in sel:
                    it.setSelected(True)
            self.verticalScrollBar().setValue(barra)
    w.__name__ = f.__name__
    return w


class Biblioteca(QListWidget):
    aviso = Signal(str)        # mensaje para la barra de estado (p. ej. duplicados omitidos)
    cambio = Signal()
    nuevos = Signal()          # se agregaron temas: hay que analizarlos
    ROL_NOMBRE = Qt.ItemDataRole.UserRole + 1
    ROL_CAB = Qt.ItemDataRole.UserRole + 2         # True en los encabezados de carpeta
    ROL_CARPETA_ORIG = Qt.ItemDataRole.UserRole + 4  # ruta ORIGINAL de la carpeta (con mayúsculas reales): para arrastrar afuera

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setUniformItemSizes(True)
        self.setItemDelegate(_DelegadoFondo(self))
        self.setAlternatingRowColors(False)                                    # todas las filas con el mismo fondo oscuro (#080b14)
        # ---- auto-ajuste al ancho de la lista (los ítems se estiran con el viewport, sin scroll horizontal) ----
        self.setResizeMode(QListView.ResizeMode.Adjust)                        # QListWidget hereda de QListView
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)                     # texto largo → "…" (el tooltip lo muestra completo)
        self.setWordWrap(False)
        # ----------------------------------------------------------------------------------------------------------
        f = self.font(); f.setPointSize(int(round(9 * FUENTE_BOOST))); self.setFont(f)
        self._rutas = set()
        self._cola = set()         # temas esperando su análisis (se muestran con ⏳)
        self._memo = {}            # ruta -> (bpm, clave Camelot, nombre de la nota, hay_clave): se lee el .json una sola vez
        self._memo_frase = {}      # ruta -> True si el tema tiene grilla de compases firme (sirve para mezclar en frase)
        self._memo_dur = {}        # ruta -> duración en segundos (del análisis)
        self._memo_voz = {}        # ruta -> True si el análisis ya trae las curvas de voz/bajo
        self._skips = {}           # ruta (normalizada) -> True si está SALTEADO (no se carga solo al mezclar)
        self._cargando = False     # guarda: bloquea reacciones a itemChanged mientras se cargan/ordenan cosas
        self.agrupado = False      # vista por carpetas: un encabezado por carpeta y debajo sus temas
        self._plegadas = set()     # carpetas cerradas (con clic en el encabezado)
        self.itemClicked.connect(self._clic_cab)
        self.itemChanged.connect(self._on_item_changed)     # checkbox "saltear"
        self._referencia = None    # clave Camelot del tema que suena: los compatibles se pintan de verde

    # ---------- saltear temas ----------
    def esta_salteado(self, ruta):
        return self._skips.get(self._clave(ruta), False)

    def todas_activas(self):
        """Todas las rutas MENOS las que están tildadas como salteadas."""
        return [r for r in self.todas() if not self.esta_salteado(r)]

    def _on_item_changed(self, it):
        if self._cargando or self._es_cab(it):
            return
        ruta = it.data(Qt.ItemDataRole.UserRole)
        k = self._clave(ruta)
        skip = (it.checkState() == Qt.CheckState.Checked)   # ← TILDADO = salteado
        if self._skips.get(k, False) == skip:
            return                                   # nada cambió (por ejemplo, disparó por setText/setData)
        self._skips[k] = skip
        self._refrescar_textos()
        self.guardar()
        self.cambio.emit()

    @staticmethod
    def _clave(p):
        return os.path.normcase(os.path.abspath(p))

    @staticmethod
    def _firma(p):
        """Identidad de un tema para detectar duplicados aunque estén en otra carpeta o se llamen "Tema (1)" / "Tema - copia":
        (nombre normalizado, tamaño del archivo). Dos archivos con el mismo nombre y el mismo tamaño son el mismo tema."""
        base = os.path.splitext(os.path.basename(p))[0].lower()
        nombre = re.sub(r"^\s*(copia|copy)\s+de\s+", "", base)                                   # "Copia de tema"
        for _ in range(3):                                                                       # "tema - copia (2)", "tema (1)"…
            nombre = re.sub(r"[\s_]*[\(\[]\s*\d+\s*[\)\]]\s*$", "", nombre)
            nombre = re.sub(r"[\s_\-]+[\(\[]?\s*(copia|copy|copie|kopie)\s*\d*\s*[\)\]]?\s*$", "", nombre)
        nombre = re.sub(r"[\s_]+", " ", nombre).strip() or base
        try:
            tam = os.path.getsize(p)
        except OSError:
            tam = -1
        return (nombre, tam)

    # ---------- vista por carpetas ----------
    def _es_cab(self, it):
        return bool(it.data(self.ROL_CAB))

    @staticmethod
    def _carpeta(ruta):
        return os.path.normcase(os.path.dirname(os.path.abspath(ruta)))

    def _quitar_cab(self):
        for i in range(self.count() - 1, -1, -1):
            if self._es_cab(self.item(i)):
                self.takeItem(i)
            else:
                self.item(i).setHidden(False)

    def _poner_cab(self):
        """Agrupa por carpeta (en orden alfabético); dentro de cada una los temas conservan el orden que tenían."""
        prev = self._cargando
        self._cargando = True
        try:
            items = [self.takeItem(0) for _ in range(self.count())]
            grupos = {}
            origs = {}                                    # ruta ORIGINAL (con mayúsculas reales) por carpeta
            for it in items:
                ruta = it.data(Qt.ItemDataRole.UserRole)
                k = self._carpeta(ruta)
                grupos.setdefault(k, []).append(it)
                if k not in origs:
                    origs[k] = os.path.dirname(os.path.abspath(ruta))
            for carpeta in sorted(grupos, key=lambda c: os.path.basename(c).lower()):
                cab = QListWidgetItem()
                cab.setData(self.ROL_CAB, True)
                cab.setData(Qt.ItemDataRole.UserRole, carpeta)
                cab.setData(self.ROL_CARPETA_ORIG, origs[carpeta])
                # Seleccionable + arrastrable: para poder arrastrar el título afuera y copiar toda la carpeta
                cab.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                f = QFont(self.font()); f.setBold(True); cab.setFont(f)
                cab.setBackground(QBrush(QColor("#17566a"))); cab.setForeground(QBrush(QColor("#d8f6ff")))
                self.addItem(cab)
                cerrada = carpeta in self._plegadas
                nombre = os.path.basename(carpeta) or carpeta
                cab.setText(("▶ " if cerrada else "▼ ") + "📁 " + nombre)
                cab.setToolTip(f"{origs[carpeta]}\n\nArrastrá este título para copiar TODA la carpeta afuera (a otra carpeta o al Escritorio).\nClic: abrir / cerrar.")
                tot = sum((self.duracion(it.data(Qt.ItemDataRole.UserRole)) or 0) for it in grupos[carpeta])
                cab.setData(Qt.ItemDataRole.UserRole + 3, f"{len(grupos[carpeta])}" + (f" / {self._fmt_dur(tot, True)}" if tot else ""))
                for it in grupos[carpeta]:
                    self.addItem(it)
                    it.setHidden(cerrada)
        finally:
            self._cargando = prev

    def _clic_cab(self, it):
        if not self._es_cab(it):
            return
        c = it.data(Qt.ItemDataRole.UserRole)
        if c in self._plegadas:
            self._plegadas.discard(c)
        else:
            self._plegadas.add(c)
        barra = self.verticalScrollBar().value()
        sel = {self._clave(x.data(Qt.ItemDataRole.UserRole)) for x in self.selectedItems()}
        self._quitar_cab(); self._poner_cab()
        for i in range(self.count()):
            x = self.item(i)
            if not self._es_cab(x) and self._clave(x.data(Qt.ItemDataRole.UserRole)) in sel:
                x.setSelected(True)
        self.verticalScrollBar().setValue(barra)

    def set_agrupado(self, v):
        v = bool(v)
        if v == self.agrupado:
            return
        if v:
            self.agrupado = True
            self._poner_cab()
        else:
            self._quitar_cab()
            self.agrupado = False
        self._refrescar_textos()
        if getattr(self, "_ult_pintado", None):
            self.pintar(*self._ult_pintado)

    # ---------- botón << (contraer / expandir todas las carpetas) ----------
    def plegar_todas(self):
        """Contrae TODAS las carpetas (vista por carpetas)."""
        if not self.agrupado:
            return
        for i in range(self.count()):
            it = self.item(i)
            if self._es_cab(it):
                self._plegadas.add(it.data(Qt.ItemDataRole.UserRole))
        self._quitar_cab()
        self._poner_cab()

    def desplegar_todas(self):
        """Expande TODAS las carpetas (vista por carpetas)."""
        if not self.agrupado:
            return
        self._plegadas.clear()
        self._quitar_cab()
        self._poner_cab()

    def todas_plegadas(self):
        """True si TODAS las carpetas están contraídas (o no hay ninguna carpeta)."""
        if not self.agrupado:
            return False
        carpetas = set()
        for i in range(self.count()):
            it = self.item(i)
            if self._es_cab(it):
                carpetas.add(it.data(Qt.ItemDataRole.UserRole))
        return bool(carpetas) and carpetas.issubset(self._plegadas)

    @staticmethod
    def _fmt_dur(seg, largo=False):
        seg = int(round(seg)); h, r = divmod(seg, 3600); m, sg = divmod(r, 60)
        return f"{h}:{m:02d}:{sg:02d}" if (h or largo) else f"{m}:{sg:02d}"

    def duracion(self, ruta):
        self.info(ruta)
        return self._memo_dur.get(self._clave(ruta))

    def _nombre(self, it):
        n = it.data(self.ROL_NOMBRE)
        return n if n is not None else it.text()

    def _refrescar_textos(self):
        prev = self._cargando
        self._cargando = True
        try:
            for i in range(self.count()):
                it = self.item(i)
                if self._es_cab(it):
                    continue
                esperando = self._clave(it.data(Qt.ItemDataRole.UserRole)) in self._cola
                bpm, clave = self.info(it.data(Qt.ItemDataRole.UserRole))[:2]
                pref = (f"{bpm:.0f} - " if bpm else "") + (f"[{clave}] " if clave else "")      # ej.: "124 - [8A] nombre del tema"
                nom = self._nombre(it)
                if bpm:                                   # el BPM ya va adelante: se saca el "[73 BPM]" que traiga el nombre del archivo
                    nom = re.sub(r"\s*[\[\(]\s*\d+(?:[.,]\d+)?\s*BPM\s*[\]\)]\s*", " ", nom, flags=re.I).strip() or nom
                salteado = self.esta_salteado(it.data(Qt.ItemDataRole.UserRole))
                prefijo = "⏭ " if salteado else ""
                nuevo = prefijo + ("⏳ " if esperando else "") + pref + nom
                if it.text() != nuevo:
                    it.setText(nuevo)
                d = self.duracion(it.data(Qt.ItemDataRole.UserRole))
                it.setData(Qt.ItemDataRole.UserRole + 3, self._fmt_dur(d) if d else None)
        finally:
            self._cargando = prev

    def marcar(self, rutas):
        """Los temas de esta lista aparecen con el reloj de arena hasta que se los analiza."""
        self._cola = {self._clave(r) for r in rutas}
        self._refrescar_textos()

    def quitar_de_cola(self, ruta):
        k = self._clave(ruta)
        self._memo.pop(k, None); self._memo_frase.pop(k, None); self._memo_voz.pop(k, None)     # terminó su análisis: se vuelve a leer
        self._cola.discard(k)
        self._refrescar_textos()
        self.pintar(*self._ult_pintado) if getattr(self, "_ult_pintado", None) else None

    def info(self, ruta):
        """(bpm, clave Camelot, nombre de la nota, hay_clave) del tema, desde su caché de análisis."""
        k = self._clave(ruta)
        v = self._memo.get(k)
        if v is None:
            bpm = cam = nom = None; hay = False; fr = False; hv = False
            try:
                cache = CACHE_DIR / (Path(ruta).stem + ".json")
                if cache.exists():
                    with open(cache, encoding="utf-8") as f:
                        d = json.load(f)
                    b = d.get("bpm"); bpm = float(b) if b is not None else None
                    fr = len(d.get("downbeats_full") or d.get("downbeats") or []) >= 9 and d.get("grid") != 0
                    hv = "voz" in d
                    try:
                        self._memo_dur[k] = float(d.get("duration") or 0) or None
                    except Exception:
                        pass
                    if "key" in d:
                        hay = True
                        cam = (d["key"] or {}).get("camelot"); nom = (d["key"] or {}).get("nombre")
            except Exception:
                pass
            v = (bpm, cam, nom, hay)
            self._memo[k] = v
            self._memo_frase[k] = bool(fr)
            self._memo_voz[k] = bool(hv)
        return v

    def frase_ok(self, ruta):
        self.info(ruta)
        return self._memo_frase.get(self._clave(ruta), False)

    @_reagrupa
    def ordenar_inteligente(self, armonico, frase, inicio=None):
        """Ordena la lista de arriba hacia abajo como una cadena de mezcla: cada tema es el que mejor engancha con el
        anterior (clave compatible primero, BPM parecido después). Con 'frase' van primero los que tienen grilla de
        compases firme. Los que todavía no tienen análisis quedan al final. `inicio`: tema donde arranca la cadena."""
        n = self.count()
        if n < 2:
            return
        barra = self.verticalScrollBar().value()
        sel = {self._clave(it.data(Qt.ItemDataRole.UserRole)) for it in self.selectedItems() if not self._es_cab(it)}
        items = [self.item(i) for i in range(n)]
        datos = []
        for it in items:
            r = it.data(Qt.ItemDataRole.UserRole)
            bpm, cam, _, hay = self.info(r)
            datos.append({"it": it, "r": r, "k": self._clave(r), "bpm": bpm, "cam": cam if armonico else None,
                          "ok": (not frase) or self.frase_ok(r), "nombre": self._nombre(it).lower()})
        listos = [d for d in datos if d["bpm"] and (d["ok"] or not frase) and (d["cam"] or not armonico)]
        resto = [d for d in datos if d not in listos]
        listos.sort(key=lambda d: (d["bpm"], d["nombre"]))
        cadena = []
        if listos:
            ini = next((d for d in listos if inicio and d["k"] == self._clave(inicio)), listos[0])
            cur = ini; listos.remove(ini); cadena.append(cur)
            while listos:
                def puntaje(d):
                    nivel = compat_armonica(cur["cam"], d["cam"]) if armonico else 0
                    dif = abs(d["bpm"] / cur["bpm"] - 1.0)
                    return ((nivel or 0) * 10.0 - dif * 150.0, -d["bpm"])
                cur = max(listos, key=puntaje)
                listos.remove(cur); cadena.append(cur)
        resto.sort(key=lambda d: (d["bpm"] is None, d["bpm"] or 0.0, d["nombre"]))     # sin clave/grilla: al final, por BPM
        orden = [d["k"] for d in cadena + resto]
        if orden == [self._clave(self.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(n)]:
            return                                              # ya está en ese orden: no se toca nada
        prev = self._cargando
        self._cargando = True
        self.setUpdatesEnabled(False)
        try:
            while self.count() > 0:
                self.takeItem(0)
            for d in cadena + resto:
                self.addItem(d["it"])
                if d["k"] in sel:
                    d["it"].setSelected(True)
        finally:
            self.setUpdatesEnabled(True)
            self._cargando = prev
        self.verticalScrollBar().setValue(barra)
        if getattr(self, "_ult_pintado", None):
            self.pintar(*self._ult_pintado)
        self.cambio.emit()

    def set_referencia(self, clave):
        if clave != self._referencia:
            self._referencia = clave
            if getattr(self, "_ult_pintado", None):
                self.pintar(*self._ult_pintado)

    def _firmas_actuales(self):
        return {self._firma(r) for r in self.todas()}

    def agregar(self, rutas):
        n = 0
        dup = 0
        firmas = self._firmas_actuales()               # lo que ya está en la lista (por nombre + tamaño)
        prev = self._cargando
        self._cargando = True
        self.setUpdatesEnabled(False)
        try:
            for p in _escanear(rutas):
                clave = os.path.normcase(os.path.abspath(p))
                if clave in self._rutas:
                    continue                           # el mismo archivo, ya está
                f = self._firma(p)
                if f in firmas:
                    dup += 1                           # una copia de un tema que ya está (otra carpeta, "(1)", "- copia"…)
                    log("biblioteca", f"duplicado omitido: {os.path.basename(p)}")
                    continue
                firmas.add(f)
                self._rutas.add(clave)
                nombre = os.path.splitext(os.path.basename(p))[0]
                it = QListWidgetItem(nombre)
                it.setData(self.ROL_NOMBRE, nombre)
                it.setData(Qt.ItemDataRole.UserRole, p)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # ← casilla TILDADA solo si venía guardado como salteado; si no, arranca DESTILDADA
                it.setCheckState(Qt.CheckState.Checked if self._skips.get(clave) else Qt.CheckState.Unchecked)
                it.setToolTip(p + "\n\nCasilla tildada = SALTEAR: la carga automática no lo pone en el reproductor.")
                self.addItem(it)
                n += 1
        finally:
            self._cargando = prev
            self.setUpdatesEnabled(True)
        if n and self.agrupado:
            self._quitar_cab(); self._poner_cab()
        if n:
            log("biblioteca", f"+{n} tema(s) agregado(s) · total {self.count()}")
            self._refrescar_textos()
            self.cambio.emit()
            self.nuevos.emit()
        if dup:
            self.aviso.emit(f"♻️ {dup} tema(s) repetido(s) no se agregaron" + (f" · {n} nuevo(s)" if n else ""))
        return n

    def quitar_seleccion(self):
        items = [it for it in self.selectedItems() if not self._es_cab(it)]      # nunca borrar los títulos de carpeta
        log("biblioteca", f"quitando {len(items)} tema(s)")
        for it in items:
            p = it.data(Qt.ItemDataRole.UserRole)
            self._rutas.discard(os.path.normcase(os.path.abspath(p)))
            self.takeItem(self.row(it))
        if self.agrupado:
            self._quitar_cab(); self._poner_cab()
        self.cambio.emit()

    def limpiar(self):
        log("biblioteca", "lista vaciada")
        self.clear(); self._rutas.clear(); self._cola.clear(); self.cambio.emit()

    def pintar(self, ruta_a, ruta_b):
        self._ult_pintado = (ruta_a, ruta_b)
        ka = os.path.normcase(os.path.abspath(ruta_a)) if ruta_a else None
        kb = os.path.normcase(os.path.abspath(ruta_b)) if ruta_b else None
        for i in range(self.count()):
            it = self.item(i)
            if self._es_cab(it):
                continue
            ruta = it.data(Qt.ItemDataRole.UserRole)
            k = os.path.normcase(os.path.abspath(ruta))
            if k == ka:
                it.setBackground(QBrush(QColor(COLOR_DECK_A))); it.setForeground(QBrush(QColor(TEMA["bg0"])))
            elif k == kb:
                it.setBackground(QBrush(QColor(COLOR_DECK_B))); it.setForeground(QBrush(QColor(TEMA["bg0"])))
            else:
                nivel = compat_armonica(self._referencia, self.info(ruta)[1]) if (self._referencia and not self.agrupado) else None     # por carpetas: sin colores de compatibilidad
                if nivel == 2:                      # misma clave o relativa
                    it.setBackground(QBrush(QColor("#0d4a30"))); it.setForeground(QBrush(QColor("#7dffbf")))
                elif nivel == 1:                    # vecina en la rueda
                    it.setBackground(QBrush(QColor("#3b4410"))); it.setForeground(QBrush(QColor("#e1ff8a")))
                else:
                    it.setData(Qt.ItemDataRole.BackgroundRole, None)
                    it.setData(Qt.ItemDataRole.ForegroundRole, None)

    def todas(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count()) if not self._es_cab(self.item(i))]

    def todas_visibles(self):
        """Todas las rutas VISIBLES ahora mismo en la lista: excluye títulos de carpeta y temas ocultos
        (por el filtro de búsqueda o por una carpeta cerrada). Es la 'cola' real de lo que el usuario ve.
        Sirve para que la carga automática (doble clic, mezcla automática, botón F2) respete el filtro."""
        return [self.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.count())
                if not self._es_cab(self.item(i)) and not self.item(i).isHidden()]

    def _bpm_de(self, ruta):
        return self.info(ruta)[0]

    def temas_sin_bpm(self):
        return [r for r in self.todas() if self._bpm_de(r) is None]

    def temas_sin_analisis(self):
        """Sin BPM, o con análisis viejo al que le falta la tonalidad."""
        out = []
        for r in self.todas():
            bpm, _, _, hay_clave = self.info(r)
            if bpm is None or not hay_clave or not self._memo_voz.get(self._clave(r), False):
                out.append(r)
        return out

    @_reagrupa
    def ordenar_por_bpm(self):
        prev = self._cargando
        self._cargando = True
        self.setUpdatesEnabled(False)
        try:
            items = []
            while self.count() > 0:
                it = self.takeItem(0)
                ruta = it.data(Qt.ItemDataRole.UserRole)
                bpm = self._bpm_de(ruta)
                items.append((bpm, it))
            items.sort(key=lambda x: (x[0] is None,
                                      x[0] if x[0] is not None else 0.0,
                                      self._nombre(x[1]).lower()))
            for _, it in items:
                self.addItem(it)
        finally:
            self.setUpdatesEnabled(True)
            self._cargando = prev
        self._refrescar_textos()
        self.cambio.emit()

    @_reagrupa
    def ordenar_por_tono(self):
        """Ordena por clave Camelot (1A, 1B, 2A, 2B … 12B); dentro de cada clave por BPM. Sin clave: al final."""
        def k(ruta, it):
            bpm, cam, _, _ = self.info(ruta)
            m = re.match(r"\s*(\d{1,2})\s*([ABab])", cam or "")
            kk = (int(m.group(1)), m.group(2).upper()) if m else None
            return (kk is None, kk or (0, ""), bpm is None, bpm or 0.0, self._nombre(it).lower())
        prev = self._cargando
        self._cargando = True
        self.setUpdatesEnabled(False)
        try:
            items = []
            while self.count() > 0:
                it = self.takeItem(0)
                items.append((k(it.data(Qt.ItemDataRole.UserRole), it), it))
            items.sort(key=lambda x: x[0])
            for _, it in items:
                self.addItem(it)
        finally:
            self.setUpdatesEnabled(True)
            self._cargando = prev
        self._refrescar_textos()
        self.cambio.emit()

    def guardar(self):
        try:
            BIBLIOTECA_JSON.parent.mkdir(exist_ok=True)
            datos = [{"ruta": r, "skip": self.esta_salteado(r)} for r in self.todas()]
            BIBLIOTECA_JSON.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print("No se pudo guardar la biblioteca:", e)

    def cargar(self):
        try:
            datos = json.loads(BIBLIOTECA_JSON.read_text(encoding="utf-8"))
            rutas = []
            self._skips = {}
            for d in datos:
                if isinstance(d, str):                       # formato viejo: solo la ruta
                    rutas.append(d)
                elif isinstance(d, dict) and d.get("ruta"):
                    rutas.append(d["ruta"])
                    if d.get("skip"):
                        self._skips[os.path.normcase(os.path.abspath(d["ruta"]))] = True
            self.agregar([r for r in rutas if os.path.isfile(r)])
        except Exception:
            pass

    # ---------- drag & drop ----------
    def mimeData(self, items):
        """Para un tema: la ruta del archivo (como antes). Para un encabezado de carpeta: la ruta ORIGINAL de la
        carpeta → al soltarla en Explorer se copia la carpeta entera con todo su contenido."""
        md = QMimeData()
        urls = []
        for i in items:
            if self._es_cab(i):
                ruta = i.data(self.ROL_CARPETA_ORIG) or i.data(Qt.ItemDataRole.UserRole)
            else:
                ruta = i.data(Qt.ItemDataRole.UserRole)
            if ruta:
                urls.append(QUrl.fromLocalFile(ruta))
        md.setUrls(urls)
        return md

    def supportedDropActions(self):
        return Qt.DropAction.CopyAction

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.source() is self or not e.mimeData().hasUrls():
            e.ignore(); return
        self.agregar([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0:                                   # lista vacía: indicación en el centro
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            f = QFont(self.font()); f.setPointSizeF(f.pointSizeF() * 1.25); f.setBold(True)
            p.setFont(f); p.setPen(QColor(TEMA["suave"]))
            r = self.viewport().rect().adjusted(16, 0, -16, 0)
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), "📂\n\nArrastrá carpetas o archivos acá")
            p.end()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Delete:
            self.quitar_seleccion()
        else:
            super().keyPressEvent(e)
