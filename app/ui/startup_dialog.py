"""Mensagens de inicialização sem caminhos privados nem tracebacks visíveis."""

import ctypes
from ctypes import wintypes


def show_startup_message(message: str) -> None:
    """Exibe uma mensagem estática mesmo se Tcl/Tk não puder ser carregado."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    message_box = user32.MessageBoxW
    message_box.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    message_box.restype = ctypes.c_int
    message_box(None, message, "StudyTimer", 0x10)
