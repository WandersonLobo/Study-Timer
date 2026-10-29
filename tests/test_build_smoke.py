"""Smoke test condicional do onedir, executado pelo script de build Windows."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.build


def test_windows_bundle_opens(tmp_path: Path) -> None:
    bundle_dir = os.environ.get("STUDYTIMER_BUILD_DIR")
    if sys.platform != "win32" or not bundle_dir:
        pytest.skip("Requer build Windows e STUDYTIMER_BUILD_DIR definido.")
    bundle = Path(bundle_dir)
    executable = bundle / "StudyTimer.exe"
    assert executable.is_file()
    assert (bundle / "_internal" / "app" / "database" / "schema.sql").is_file()
    assert (bundle / "_internal" / "assets" / "studytimer.ico").is_file()
    assert (bundle / "_internal" / "customtkinter" / "assets").is_dir()
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(tmp_path)
    process = subprocess.Popen([str(executable)], env=environment, cwd=tmp_path)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        assert (tmp_path / "StudyTimer" / "estudos.db").is_file()
        assert (tmp_path / "StudyTimer" / "logs" / "studytimer.log").is_file()
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
