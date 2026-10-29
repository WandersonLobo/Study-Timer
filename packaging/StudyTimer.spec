# -*- mode: python ; coding: utf-8 -*-
"""Fonte única de configuração do pacote Windows onedir."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
icon = root / "assets" / "studytimer.ico"

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=collect_data_files("customtkinter")
    + [(str(root / "app" / "database" / "schema.sql"), "app/database"),
       (str(icon), "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StudyTimer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="StudyTimer")
