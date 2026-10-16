"""AutoMix — tecla F2 global (Windows)."""
import sys
from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QTimer


# =====================================================================
# 6) VENTANA PRINCIPAL
# =====================================================================
class TeclaGlobalF2(QAbstractNativeEventFilter):
    """Tecla F2 "global" en Windows (RegisterHotKey): funciona aunque el reproductor esté en segundo plano."""
    ID = 0xA7F2
    WM_HOTKEY = 0x0312
    VK_F2 = 0x71

    def __init__(self, accion):
        super().__init__()
        self.accion = accion
        self.activa = False

    def registrar(self):
        if sys.platform != "win32" or self.activa:
            return self.activa
        try:
            import ctypes
            if ctypes.windll.user32.RegisterHotKey(None, self.ID, 0x4000, self.VK_F2):   # 0x4000 = sin repetir al mantenerla
                QCoreApplication.instance().installNativeEventFilter(self)
                self.activa = True
        except Exception:
            self.activa = False
        return self.activa

    def quitar(self):
        if not self.activa:
            return
        try:
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, self.ID)
            QCoreApplication.instance().removeNativeEventFilter(self)
        except Exception:
            pass
        self.activa = False

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == self.WM_HOTKEY and msg.wParam == self.ID:
                    QTimer.singleShot(0, self.accion)
        except Exception:
            pass
        return False, 0
