"""Notificações de energia na thread da janela, sem SQL ou diálogos no WndProc."""

import ctypes
import logging
import sys
from collections.abc import Callable
from typing import Any

WM_POWERBROADCAST = 0x0218
WM_NCDESTROY = 0x0082
PBT_APMSUSPEND = 4
PBT_APMRESUMECRITICAL = 6
PBT_APMRESUMESUSPEND = 7
PBT_APMRESUMEAUTOMATIC = 18
POWER_EVENTS = frozenset(
    (PBT_APMSUSPEND, PBT_APMRESUMECRITICAL, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC)
)
SubclassProc = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    ctypes.c_ssize_t,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
    ctypes.c_size_t,
    ctypes.c_size_t,
)
logger = logging.getLogger("studytimer.power")


class WindowsPowerMonitor:
    """Mantém vivo o callback nativo até a remoção da subclasse da janela.

    start/close e o callback executam na thread dona do HWND. A notificação
    congela o relógio imediatamente; o próximo callback Tk persiste a pausa.
    """

    def __init__(self, on_interrupt: Callable[[], None]) -> None:
        self._on_interrupt = on_interrupt
        self._pending = False
        self._hwnd: int | None = None
        self._registration: int | None = None
        self._user32: Any = None
        self._comctl32: Any = None
        self._callback = SubclassProc(self._window_proc)

    @property
    def pending(self) -> bool:
        return self._pending

    def take_pending(self) -> bool:
        """Agrupa eventos repetidos sem criar retomada ou intervalos adicionais."""
        pending, self._pending = self._pending, False
        return pending

    def notify(self, event: int) -> bool:
        """Congela antes de qualquer tick, inclusive se faltou o evento de suspensão."""
        if event not in POWER_EVENTS:
            return False
        self._pending = True
        self._on_interrupt()
        return True

    def start(self, hwnd: int) -> None:
        """Registra o HWND externo do Tk com assinaturas compatíveis com x64."""
        if self._hwnd is not None:
            raise RuntimeError("Monitor de energia já registrado.")
        if sys.platform != "win32":
            raise RuntimeError("Monitor de energia exige Windows.")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
        self._user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self._user32.GetAncestor.restype = ctypes.c_void_p
        self._user32.RegisterSuspendResumeNotification.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self._user32.RegisterSuspendResumeNotification.restype = ctypes.c_void_p
        self._user32.UnregisterSuspendResumeNotification.argtypes = [ctypes.c_void_p]
        self._user32.UnregisterSuspendResumeNotification.restype = ctypes.c_int
        self._comctl32.SetWindowSubclass.argtypes = [
            ctypes.c_void_p,
            SubclassProc,
            ctypes.c_size_t,
            ctypes.c_size_t,
        ]
        self._comctl32.SetWindowSubclass.restype = ctypes.c_int
        self._comctl32.RemoveWindowSubclass.argtypes = [
            ctypes.c_void_p,
            SubclassProc,
            ctypes.c_size_t,
        ]
        self._comctl32.RemoveWindowSubclass.restype = ctypes.c_int
        self._comctl32.DefSubclassProc.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        self._comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
        outer = self._user32.GetAncestor(hwnd, 2)  # GA_ROOT: wrapper externo do Tk.
        if not outer or not self._comctl32.SetWindowSubclass(outer, self._callback, id(self), 0):
            raise OSError("Não foi possível observar eventos de energia.")
        self._hwnd = int(outer)
        registration = self._user32.RegisterSuspendResumeNotification(outer, 0)
        if not registration:
            self.close()
            raise OSError("Não foi possível registrar notificações de energia.")
        self._registration = int(registration)

    def close(self) -> None:
        """Libera registro e subclasse antes de destruir a janela; permite repetir."""
        if self._registration is not None:
            if not self._user32.UnregisterSuspendResumeNotification(self._registration):
                raise OSError("Não foi possível liberar notificações de energia.")
            self._registration = None
        if self._hwnd is not None:
            if not self._comctl32.RemoveWindowSubclass(self._hwnd, self._callback, id(self)):
                raise OSError("Não foi possível liberar o monitor de energia.")
            self._hwnd = None

    def _window_proc(
        self,
        hwnd: int,
        message: int,
        wparam: int,
        lparam: int,
        subclass_id: int,
        ref_data: int,
    ) -> int:
        try:
            if message == WM_POWERBROADCAST and self.notify(wparam):
                return 1
            if message == WM_NCDESTROY:
                self.close()
        except Exception as error:
            # Exceções nunca atravessam a fronteira C; nenhum texto privado no log.
            logger.error("POWER_CALLBACK_FAILED type=%s", type(error).__name__)
        try:
            return int(self._comctl32.DefSubclassProc(hwnd, message, wparam, lparam))
        except Exception as error:
            logger.error("POWER_FORWARD_FAILED type=%s", type(error).__name__)
            return 0
