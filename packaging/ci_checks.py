"""Pré-condições, contratos JUnit e artefatos públicos mínimos da CI."""

from __future__ import annotations

import argparse
import binascii
import ctypes
import json
import os
import platform
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Execução direta por caminho mantém importações de testes locais explícitas.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUALITY_MODULES = {
    "tests.test_clock",
    "tests.test_timer",
    "tests.test_migrations",
    "tests.test_period_reports",
    "tests.test_session_sequences",
}
SMOKE_CASES = {
    f"test_windows_bundle_opens_migrates_and_preserves_data[{mode}-{origin}]"
    for mode in ("light", "dark")
    for origin in ("new", "v1", "v2")
}
DESKTOP_CASES = {
    f"test_packaged_{scenario}[{mode}]"
    for scenario in ("user_cycle", "recovery")
    for mode in ("light", "dark")
}


def preflight(kind: str, output: Path | None = None) -> None:
    """Falha antes da coleta quando o executor não oferece o ambiente exigido."""
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise RuntimeError("A validação requer Windows e Python 3.12 x64.")
    metadata: dict[str, str] = {
        "kind": kind,
        "python": platform.python_version(),
        "windows": platform.release(),
        "runner_image": os.environ.get("ImageOS", "local"),
    }
    if kind in {"native", "desktop"}:
        import tkinter

        root = tkinter.Tk()
        try:
            root.withdraw()
            root.update()
            metadata["tk"] = str(root.tk.call("info", "patchlevel"))
        finally:
            root.destroy()
    if kind == "native" and os.environ.get("STUDYTIMER_NATIVE_UI") != "1":
        raise RuntimeError("A validação Tk exige opt-in ativo, sem skips.")
    if kind == "desktop":
        if os.environ.get("STUDYTIMER_DESKTOP_E2E") != "1":
            raise RuntimeError("O fluxo do executável exige opt-in de desktop.")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.OpenInputDesktop.argtypes = (ctypes.c_uint, ctypes.c_bool, ctypes.c_uint)
        user32.OpenInputDesktop.restype = ctypes.c_void_p
        user32.CloseDesktop.argtypes = (ctypes.c_void_p,)
        handle = user32.OpenInputDesktop(0, False, 1)
        if not handle:
            raise RuntimeError("Desktop interativo indisponível ou bloqueado.")
        try:
            size = ctypes.c_uint()
            user32.GetUserObjectInformationW.argtypes = (
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.POINTER(ctypes.c_uint),
            )
            name = ctypes.create_unicode_buffer(256)
            if not user32.GetUserObjectInformationW(
                handle, 2, name, ctypes.sizeof(name), ctypes.byref(size)
            ):
                raise RuntimeError("Não foi possível verificar o desktop de entrada.")
            if name.value.casefold() != "default":
                raise RuntimeError("O desktop de entrada não está disponível para os testes.")
        finally:
            user32.CloseDesktop(handle)
        if user32.GetSystemMetrics(0) < 900 or user32.GetSystemMetrics(1) < 600:
            raise RuntimeError("O desktop deve comportar pelo menos 900×600.")
        metadata["desktop"] = "interactive"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_junit(path: Path, group: str, mode: str | None = None) -> int:
    """Confere coleta efetiva, ausência de skips e os grupos críticos esperados."""
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases or any(
        case.find(tag) is not None for case in cases for tag in ("skipped", "failure", "error")
    ):
        raise ValueError("Relatório vazio, com falhas ou testes pulados.")
    modules = {case.get("classname", "") for case in cases}
    if group == "quality" and not QUALITY_MODULES <= modules:
        raise ValueError("Faltam grupos críticos de regras e persistência.")
    if group == "native":
        from tests.native_manifest import NATIVE_SCENARIOS

        modes = (mode,) if mode is not None else ("light", "dark")
        expected = {
            f"test_native_scenario[{scenario}-{appearance}]"
            for scenario in NATIVE_SCENARIOS
            for appearance in modes
        }
        names = [case.get("name", "") for case in cases]
        if set(names) != expected or len(names) != len(expected):
            raise ValueError("A matriz Tk não foi executada integralmente.")
    if group in {"smoke", "build"}:
        smoke = [
            case.get("name", "")
            for case in cases
            if case.get("classname") == "tests.test_build_smoke"
        ]
        if set(smoke) != SMOKE_CASES or len(smoke) != len(SMOKE_CASES):
            raise ValueError("A matriz de abertura/migração não foi executada integralmente.")
        if group == "build":
            desktop = [
                case.get("name", "")
                for case in cases
                if case.get("classname") == "tests.test_packaged_ui"
            ]
            if set(desktop) != DESKTOP_CASES or len(desktop) != len(DESKTOP_CASES):
                raise ValueError("A matriz externa não foi executada integralmente.")
    return len(cases)


def _minimal_png(data: bytes) -> bytes:
    """Descarta metadados e recusa PNGs truncados ou com chunks corrompidos."""
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise ValueError("Captura inválida.")
    safe = bytearray(signature)
    offset = 8
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        end = offset + length + 12
        if end > len(data):
            break
        kind = data[offset + 4 : offset + 8]
        content = data[offset + 8 : end - 4]
        crc = int.from_bytes(data[end - 4 : end], "big")
        if binascii.crc32(kind + content) != crc:
            raise ValueError("Captura corrompida.")
        if kind in {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}:
            safe.extend(data[offset:end])
        if kind == b"IEND":
            return bytes(safe)
        offset = end
    raise ValueError("Captura incompleta.")


def export_artifacts(raw: Path, public: Path) -> None:
    """Publica somente JUnit mínimo, metadata conhecida e PNG da janela de teste."""
    raw, public = raw.resolve(), public.resolve()
    if raw == public or raw in public.parents or public in raw.parents:
        raise ValueError("Diretórios bruto/público devem ser separados.")
    public.mkdir(parents=True, exist_ok=True)
    if not raw.is_dir():
        return
    for source in raw.rglob("*"):
        if not source.is_file() or source.is_symlink():
            continue
        relative = source.relative_to(raw)
        if not re.fullmatch(r"[a-zA-Z0-9_./-]+", relative.as_posix()):
            continue
        destination = public / relative
        if source.suffix == ".xml":
            parsed = ET.parse(source).getroot()
            cases = list(parsed.iter("testcase"))
            safe = ET.Element(
                "testsuite",
                name="StudyTimer",
                tests=str(len(cases)),
                attrib={
                    tag: str(sum(case.find(element) is not None for case in cases))
                    for tag, element in (
                        ("failures", "failure"),
                        ("errors", "error"),
                        ("skipped", "skipped"),
                    )
                },
            )
            for case in cases:
                name = case.get("name", "test")
                function, _, params = name.partition("[")
                if not re.fullmatch(r"[a-zA-Z0-9_]+", function):
                    function = "test"
                safe_name = function if not re.fullmatch(r"[a-zA-Z0-9_-]+\]", params) else name
                if function == "test":
                    safe_name = "test"
                classname = case.get("classname", "tests")
                if not re.fullmatch(r"[a-zA-Z0-9_.]+", classname):
                    classname = "tests"
                target = ET.SubElement(safe, "testcase", name=safe_name, classname=classname)
                for tag in ("skipped", "error", "failure"):
                    if case.find(tag) is not None:
                        element = ET.SubElement(target, tag)
                        element.text = (
                            "Consulte o resultado da execução; conteúdo bruto não publicado."
                        )
            destination.parent.mkdir(parents=True, exist_ok=True)
            ET.ElementTree(safe).write(destination, encoding="utf-8", xml_declaration=True)
        elif source.suffix == ".json":
            values = json.loads(source.read_text(encoding="utf-8"))
            safe_values = {
                key: str(values[key])
                for key in ("kind", "python", "windows", "runner_image", "tk", "desktop")
                if key in values and re.fullmatch(r"[a-zA-Z0-9_. -]{1,80}", str(values[key]))
            }
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(safe_values, indent=2), encoding="utf-8")
        elif source.suffix == ".png":
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(_minimal_png(source.read_bytes()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    before = commands.add_parser("preflight")
    before.add_argument("--kind", choices=("quality", "native", "desktop"), required=True)
    before.add_argument("--output", type=Path)
    report = commands.add_parser("verify")
    report.add_argument("path", type=Path)
    report.add_argument("--group", choices=("quality", "native", "build", "smoke"), required=True)
    report.add_argument("--mode", choices=("light", "dark"))
    artifact = commands.add_parser("export")
    artifact.add_argument("raw", type=Path)
    artifact.add_argument("public", type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args.kind, args.output)
    elif args.command == "verify":
        print(f"Casos confirmados: {validate_junit(args.path, args.group, args.mode)}")
    else:
        export_artifacts(args.raw, args.public)


if __name__ == "__main__":
    main()
