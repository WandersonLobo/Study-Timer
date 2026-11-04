"""Entrada Win32 e captura restrita às janelas do processo de teste.

Não importa objetos do aplicativo nem controla processos fora do PID informado.
As coordenadas são relativas ao cliente em 900x600, com DPI explícito.
"""

from __future__ import annotations

import ctypes
import struct
import time
import zlib
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path


class DesktopUnavailable(RuntimeError):
    """A sessão não permite enviar entradas ao desktop interativo."""


class Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("vk", wintypes.WORD),
        ("scan", wintypes.WORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra", ctypes.c_size_t),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("data", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra", ctypes.c_size_t),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(ctypes.Structure):
    _anonymous_ = ("payload",)
    _fields_ = [("kind", wintypes.DWORD), ("payload", InputUnion)]


class BitmapHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("width", wintypes.LONG),
        ("height", wintypes.LONG),
        ("planes", wintypes.WORD),
        ("bits", wintypes.WORD),
        ("compression", wintypes.DWORD),
        ("image_size", wintypes.DWORD),
        ("xppm", wintypes.LONG),
        ("yppm", wintypes.LONG),
        ("used", wintypes.DWORD),
        ("important", wintypes.DWORD),
    ]


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("pid", wintypes.DWORD),
        ("heap", ctypes.c_size_t),
        ("module", wintypes.DWORD),
        ("threads", wintypes.DWORD),
        ("parent", wintypes.DWORD),
        ("priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
        ("filename", wintypes.WCHAR * 260),
    ]


def process_family(pid: int) -> set[int]:
    """Inclui somente filhos do processo lançado (redirector da venv/bootloader)."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise DesktopUnavailable("Não foi possível identificar o processo de teste.")
    entries: list[tuple[int, int]] = []
    entry = ProcessEntry()
    entry.size = ctypes.sizeof(ProcessEntry)
    try:
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            entries.append((int(entry.pid), int(entry.parent)))
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    family = {pid}
    while True:
        updated = family | {child for child, parent in entries if parent in family}
        if updated == family:
            return family
        family = updated


def _user32() -> ctypes.WinDLL:
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(Rect))
    user.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(Rect))
    user.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(Point))
    user.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user.BringWindowToTop.argtypes = (wintypes.HWND,)
    user.GetDpiForWindow.argtypes = (wintypes.HWND,)
    user.GetDpiForWindow.restype = wintypes.UINT
    user.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    user.SetWindowPos.argtypes = (
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    )
    user.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
    user.SendInput.restype = wintypes.UINT
    user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.GetWindowDC.argtypes = (wintypes.HWND,)
    user.GetWindowDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    user.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    user.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.WindowFromPoint.argtypes = (Point,)
    user.WindowFromPoint.restype = wintypes.HWND
    user.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(Point))
    return user


def wait_until(
    condition: Callable[[], bool],
    *,
    timeout: float = 10.0,
    message: str = "A condição esperada não foi observada.",
) -> None:
    """Espera uma condição externa; não pressupõe duração exata do cronômetro."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.025)
    raise AssertionError(message)


def window_title(hwnd: int) -> str:
    user = _user32()
    size = user.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(size + 1)
    user.GetWindowTextW(hwnd, buffer, size + 1)
    return buffer.value


def windows_for_pid(pid: int) -> list[int]:
    user = _user32()
    family = process_family(pid)
    windows: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd: int, parameter: int) -> bool:
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in family and user.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True

    callback = callback_type(collect)
    user.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user.EnumWindows(callback, 0)
    return windows


def find_window(pid: int, title: str = "StudyTimer", *, timeout: float = 15.0) -> int:
    matches: list[int] = []

    def locate() -> bool:
        matches[:] = [hwnd for hwnd in windows_for_pid(pid) if window_title(hwnd) == title]
        return bool(matches)

    wait_until(locate, timeout=timeout, message="A janela esperada do aplicativo não apareceu.")
    return matches[0]


def close_window(hwnd: int) -> None:
    _user32().PostMessageW(hwnd, 0x0010, 0, 0)


def capture_window(hwnd: int, output: Path) -> None:
    """Captura PrintWindow em PNG; nunca captura o desktop ou outras janelas."""
    user = _user32()
    rect = Rect()
    if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise DesktopUnavailable("Não foi possível medir a janela de teste.")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0 or width * height > 20_000_000:
        raise DesktopUnavailable("Dimensão inválida para a captura da janela.")
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    gdi.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    gdi.DeleteDC.argtypes = (wintypes.HDC,)
    gdi.GetDIBits.argtypes = (
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BitmapHeader),
        wintypes.UINT,
    )
    dc = user.GetWindowDC(hwnd)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    previous = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory, 2):
            raise DesktopUnavailable("A captura da janela não foi aceita pelo Windows.")
        gdi.SelectObject(memory, previous)
        header = BitmapHeader(ctypes.sizeof(BitmapHeader), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0) != height:
            raise DesktopUnavailable("Não foi possível ler a captura da janela.")
        raw = pixels.raw
        rows = []
        for y in range(height):
            line = raw[y * width * 4 : (y + 1) * width * 4]
            rgb = bytearray(width * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
            rows.append(b"\x00" + rgb)

        def chunk(kind: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data))
            )

        content = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows)))
            + chunk(b"IEND", b"")
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
    finally:
        gdi.SelectObject(memory, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, dc)


class Desktop:
    """Emite entrada somente após comprovar foco da janela do PID de teste."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.user = _user32()
        self.user.SetProcessDPIAware()

    def focus(self, hwnd: int) -> None:
        owner = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value not in process_family(self.pid):
            raise DesktopUnavailable("A janela não pertence ao processo de teste.")
        self.user.ShowWindow(hwnd, 9)
        self.user.BringWindowToTop(hwnd)
        self.user.SetForegroundWindow(hwnd)
        if int(self.user.GetForegroundWindow() or 0) != hwnd:
            # O Windows pode manter o bloqueio de foreground do lançador da CI.
            # Compartilhar temporariamente a fila não envia teclas ao lançador.
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentThreadId.restype = wintypes.DWORD
            current = kernel.GetCurrentThreadId()
            foreground = self.user.GetForegroundWindow()
            thread = self.user.GetWindowThreadProcessId(foreground, None) if foreground else 0
            attached = bool(thread and self.user.AttachThreadInput(current, thread, True))
            try:
                self.user.BringWindowToTop(hwnd)
                self.user.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    self.user.AttachThreadInput(current, thread, False)
        wait_until(
            lambda: int(self.user.GetForegroundWindow() or 0) == hwnd,
            timeout=3,
            message="O desktop não permitiu focar a janela de teste.",
        )

    def size(self, hwnd: int, *, focus: bool = True) -> None:
        """Fixa cliente lógico 900x600 e recusa um desktop menor que a janela."""
        if hwnd not in windows_for_pid(self.pid):
            raise DesktopUnavailable("A janela não pertence ao processo de teste.")
        dpi = int(self.user.GetDpiForWindow(hwnd) or 96)
        width, height = round(900 * dpi / 96), round(600 * dpi / 96)
        rect = Rect(0, 0, width, height)
        style = self.user.GetWindowLongW(hwnd, -16)
        exstyle = self.user.GetWindowLongW(hwnd, -20)
        self.user.AdjustWindowRectExForDpi.argtypes = (
            ctypes.POINTER(Rect),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.UINT,
        )
        self.user.AdjustWindowRectExForDpi(ctypes.byref(rect), style, False, exstyle, dpi)
        outer_w, outer_h = rect.right - rect.left, rect.bottom - rect.top
        if self.user.GetSystemMetrics(0) < outer_w or self.user.GetSystemMetrics(1) < outer_h:
            raise DesktopUnavailable("O desktop deve comportar a janela lógica 900x600.")
        flags = 0x0040 | (0 if focus else 0x0010)  # SWP_SHOWWINDOW | SWP_NOACTIVATE
        self.user.SetWindowPos(hwnd, None, 0, 0, outer_w, outer_h, flags)
        if focus:
            self.focus(hwnd)

        def sized() -> bool:
            client = Rect()
            self.user.GetClientRect(hwnd, ctypes.byref(client))
            return bool(abs(client.right - width) <= 2 and abs(client.bottom - height) <= 2)

        wait_until(sized, timeout=5, message="A janela não atingiu o tamanho de teste.")

    def _send(self, inputs: list[Input]) -> None:
        owner = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), ctypes.byref(owner))
        if owner.value not in process_family(self.pid):
            raise DesktopUnavailable("O processo de teste perdeu o foco antes da entrada.")
        data = (Input * len(inputs))(*inputs)
        if self.user.SendInput(len(inputs), data, ctypes.sizeof(Input)) != len(inputs):
            error = ctypes.get_last_error()
            raise DesktopUnavailable(f"SendInput não foi aceito na sessão gráfica (Win32 {error}).")

    def key(self, key: int, *, control: bool = False, shift: bool = False) -> None:
        sequence = []
        modifiers = ([0x11] if control else []) + ([0x10] if shift else [])
        for value in modifiers:
            sequence.append(Input(1, InputUnion(keyboard=KeyboardInput(value, 0, 0, 0, 0))))
        sequence.extend(
            (
                Input(1, InputUnion(keyboard=KeyboardInput(key, 0, 0, 0, 0))),
                Input(1, InputUnion(keyboard=KeyboardInput(key, 0, 2, 0, 0))),
            )
        )
        for value in reversed(modifiers):
            sequence.append(Input(1, InputUnion(keyboard=KeyboardInput(value, 0, 2, 0, 0))))
        self._send(sequence)

    def type_text(self, text: str) -> None:
        encoded = text.encode("utf-16-le")
        inputs: list[Input] = []
        for offset in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[offset : offset + 2], "little")
            inputs.extend(
                (
                    Input(1, InputUnion(keyboard=KeyboardInput(0, unit, 4, 0, 0))),
                    Input(1, InputUnion(keyboard=KeyboardInput(0, unit, 6, 0, 0))),
                )
            )
        self._send(inputs)

    def click(self, hwnd: int, x: float, y: float) -> None:
        """Ponto relativo ao cliente; nunca posição absoluta do desenvolvedor."""
        if not 0 < x < 1 or not 0 < y < 1:
            raise ValueError("O ponto de entrada deve ficar dentro do cliente da janela.")
        self.focus(hwnd)
        rect = Rect()
        if (
            not self.user.GetClientRect(hwnd, ctypes.byref(rect))
            or not rect.right
            or not rect.bottom
        ):
            raise DesktopUnavailable("Não foi possível medir o controle de entrada.")
        point = Point(round(rect.right * x), round(rect.bottom * y))
        if not self.user.ClientToScreen(hwnd, ctypes.byref(point)):
            raise DesktopUnavailable("Não foi possível localizar o ponto na janela própria.")
        self._click_point(point)

    def _click_point(self, point: Point) -> None:
        owner = wintypes.DWORD()
        target = self.user.WindowFromPoint(point)
        self.user.GetWindowThreadProcessId(target, ctypes.byref(owner))
        if owner.value not in process_family(self.pid):
            raise DesktopUnavailable("O ponto de entrada não pertence à janela de teste.")
        width, height = self.user.GetSystemMetrics(0), self.user.GetSystemMetrics(1)
        if not 0 <= point.x < width or not 0 <= point.y < height:
            raise DesktopUnavailable("O controle deve ficar dentro do monitor principal de teste.")
        # Movimento e botões entram juntos na fila. SetCursorPos separado pode
        # mover o ponteiro para o clique seguinte antes de processar o primeiro.
        self._send(
            [
                Input(
                    0,
                    InputUnion(
                        mouse=MouseInput(
                            round(point.x * 65535 / (width - 1)),
                            round(point.y * 65535 / (height - 1)),
                            0,
                            0x8001,
                            0,
                            0,
                        )
                    ),
                ),
                Input(0, InputUnion(mouse=MouseInput(0, 0, 0, 2, 0, 0))),
                Input(0, InputUnion(mouse=MouseInput(0, 0, 0, 4, 0, 0))),
            ]
        )

    def pixel(self, hwnd: int, x: float, y: float) -> tuple[int, int, int]:
        """Lê um pixel do cliente próprio para aguardar estados visuais externos."""
        if hwnd not in windows_for_pid(self.pid):
            raise DesktopUnavailable("A janela não pertence ao processo de teste.")
        rect = Rect()
        self.user.GetClientRect(hwnd, ctypes.byref(rect))
        point = Point(round(rect.right * x), round(rect.bottom * y))
        self.user.ClientToScreen(hwnd, ctypes.byref(point))
        child = self.user.WindowFromPoint(point)
        owner = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(child, ctypes.byref(owner))
        if owner.value not in process_family(self.pid):
            raise DesktopUnavailable("O ponto observado não pertence à janela de teste.")
        if not self.user.ScreenToClient(child, ctypes.byref(point)):
            raise DesktopUnavailable("Não foi possível localizar o pixel do controle próprio.")
        self.user.GetDC.argtypes = (wintypes.HWND,)
        self.user.GetDC.restype = wintypes.HDC
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi.GetPixel.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
        gdi.GetPixel.restype = wintypes.DWORD
        dc = self.user.GetDC(child)
        try:
            color = int(gdi.GetPixel(dc, point.x, point.y))
            if color == 0xFFFFFFFF:
                raise DesktopUnavailable("O desktop não permite observar a janela de teste.")
            return color & 255, (color >> 8) & 255, (color >> 16) & 255
        finally:
            self.user.ReleaseDC(child, dc)

    def choose_menu(self, hwnd: int, x: float, y: float, item: int, *, count: int = 2) -> None:
        """Abre opção CTk e escolhe no menu Win32 pertencente ao processo próprio."""
        if not 0 <= item < count:
            raise ValueError("Índice inválido do menu de teste.")
        self.click(hwnd, x, y)
        menus: list[int] = []

        def opened() -> bool:
            menus.clear()
            for candidate in windows_for_pid(self.pid):
                name = ctypes.create_unicode_buffer(128)
                self.user.GetClassNameW(candidate, name, len(name))
                if name.value == "#32768":
                    menus.append(candidate)
            return len(menus) == 1

        wait_until(opened, timeout=5, message="O menu nativo da opção não apareceu.")
        rect = Rect()
        if (
            not self.user.GetClientRect(menus[0], ctypes.byref(rect))
            or not rect.right
            or not rect.bottom
        ):
            raise DesktopUnavailable("Não foi possível medir o menu nativo.")
        point = Point(rect.right // 2, round(rect.bottom * (item + 0.5) / count))
        if not self.user.ClientToScreen(menus[0], ctypes.byref(point)):
            raise DesktopUnavailable("Não foi possível localizar o item do menu próprio.")
        # O menu mantém a janela principal como foreground; focar a janela de
        # popup explicitamente fecharia o menu. _send ainda verifica o PID.
        self._click_point(point)
        wait_until(lambda: menus[0] not in windows_for_pid(self.pid), timeout=5)
