"""AutoMix — lista de temas (biblioteca)."""
from pathlib import Path
import json
import os
import re
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QStyledItemDelegate
from PySide6.QtGui import QBrush, QColor, QPainter
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
        super().paint(painter, option, index)




class Biblioteca(QListWidget):
    aviso = Signal(str)        # mensaje para la barra de estado (p. ej. duplicados omitidos)
    cambio = Signal()
    nuevos = Signal()          # se agregaron temas: hay que analizarlos
    ROL_NOMBRE = Qt.ItemDataRole.UserRole + 1

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setUniformItemSizes(True)
        self.setItemDelegate(_DelegadoFondo(self))
        self.setAlternatingRowColors(True)
        f = self.font(); f.setPointSize(int(round(9 * FUENTE_BOOST))); self.setFont(f)
        self._rutas = set()
        self._cola = set()         # temas esperando su análisis (se muestran con ⏳)
        self._memo = {}            # ruta -> (bpm, clave Camelot, nombre de la nota, hay_clave): se lee el .json una sola vez
        self._memo_frase = {}      # ruta -> True si el tema tiene grilla de compases firme (sirve para mezclar en frase)
        self._memo_voz = {}        # ruta -> True si el análisis ya trae las curvas de voz/bajo
        self._referencia = None    # clave Camelot del tema que suena: los compatibles se pintan de verde

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

    def _nombre(self, it):
        n = it.data(self.ROL_NOMBRE)
        return n if n is not None else it.text()

    def _refrescar_textos(self):
        for i in range(self.count()):
            it = self.item(i)
            esperando = self._clave(it.data(Qt.ItemDataRole.UserRole)) in self._cola
            bpm, clave = self.info(it.data(Qt.ItemDataRole.UserRole))[:2]
            pref = (f"{bpm:.0f} - " if bpm else "") + (f"[{clave}] " if clave else "")      # ej.: "124 - [8A] nombre del tema"
            nom = self._nombre(it)
            if bpm:                                   # el BPM ya va adelante: se saca el "[73 BPM]" que traiga el nombre del archivo
                nom = re.sub(r"\s*[\[\(]\s*\d+(?:[.,]\d+)?\s*BPM\s*[\]\)]\s*", " ", nom, flags=re.I).strip() or nom
            nuevo = ("⏳ " if esperando else "") + pref + nom
            if it.text() != nuevo:
                it.setText(nuevo)

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

    def ordenar_inteligente(self, armonico, frase, inicio=None):
        """Ordena la lista de arriba hacia abajo como una cadena de mezcla: cada tema es el que mejor engancha con el
        anterior (clave compatible primero, BPM parecido después). Con 'frase' van primero los que tienen grilla de
        compases firme. Los que todavía no tienen análisis quedan al final. `inicio`: tema donde arranca la cadena."""
        n = self.count()
        if n < 2:
            return
        barra = self.verticalScrollBar().value()
        sel = {self._clave(it.data(Qt.ItemDataRole.UserRole)) for it in self.selectedItems()}
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
        return {self._firma(self.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.count())}

    def agregar(self, rutas):
        n = 0
        dup = 0
        firmas = self._firmas_actuales()               # lo que ya está en la lista (por nombre + tamaño)
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
                it.setToolTip(p)
                self.addItem(it)
                n += 1
        finally:
            self.setUpdatesEnabled(True)
        if n:
            log("biblioteca", f"+{n} tema(s) agregado(s) · total {self.count()}")
            self._refrescar_textos()
            self.cambio.emit()
            self.nuevos.emit()
        if dup:
            self.aviso.emit(f"♻️ {dup} tema(s) repetido(s) no se agregaron" + (f" · {n} nuevo(s)" if n else ""))
        return n

    def quitar_seleccion(self):
        log("biblioteca", f"quitando {len(self.selectedItems())} tema(s)")
        for it in self.selectedItems():
            p = it.data(Qt.ItemDataRole.UserRole)
            self._rutas.discard(os.path.normcase(os.path.abspath(p)))
            self.takeItem(self.row(it))
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
            ruta = it.data(Qt.ItemDataRole.UserRole)
            k = os.path.normcase(os.path.abspath(ruta))
            if k == ka:
                it.setBackground(QBrush(QColor(COLOR_DECK_A))); it.setForeground(QBrush(QColor(TEMA["bg0"])))
            elif k == kb:
                it.setBackground(QBrush(QColor(COLOR_DECK_B))); it.setForeground(QBrush(QColor(TEMA["bg0"])))
            else:
                nivel = compat_armonica(self._referencia, self.info(ruta)[1]) if self._referencia else None
                if nivel == 2:                      # misma clave o relativa
                    it.setBackground(QBrush(QColor("#0d4a30"))); it.setForeground(QBrush(QColor("#7dffbf")))
                elif nivel == 1:                    # vecina en la rueda
                    it.setBackground(QBrush(QColor("#3b4410"))); it.setForeground(QBrush(QColor("#e1ff8a")))
                else:
                    it.setData(Qt.ItemDataRole.BackgroundRole, None)
                    it.setData(Qt.ItemDataRole.ForegroundRole, None)

    def todas(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

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

    def ordenar_por_bpm(self):
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
        self._refrescar_textos()
        self.cambio.emit()

    def guardar(self):
        try:
            BIBLIOTECA_JSON.parent.mkdir(exist_ok=True)
            BIBLIOTECA_JSON.write_text(json.dumps(self.todas(), ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print("No se pudo guardar la biblioteca:", e)

    def cargar(self):
        try:
            rutas = json.loads(BIBLIOTECA_JSON.read_text(encoding="utf-8"))
            self.agregar([r for r in rutas if os.path.isfile(r)])
        except Exception:
            pass

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(i.data(Qt.ItemDataRole.UserRole)) for i in items])
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

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Delete:
            self.quitar_seleccion()
        else:
            super().keyPressEvent(e)
