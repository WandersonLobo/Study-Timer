"""Smoke do pacote real, com perfis temporários e migração legada."""

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.database.connection import initialize_database
from app.database.health import validate_database
from tests.windows_input import close_window, window_title, windows_for_pid

pytestmark = pytest.mark.build


def _prepare_data(path: Path, origin: str, mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if origin == "new":
        return
    if origin == "v1":
        database = sqlite3.connect(path, isolation_level=None)
        schema = Path(__file__).parent / "fixtures" / "schema_v1.sql"
        database.executescript(schema.read_text(encoding="utf-8"))
    else:
        database = initialize_database(path)
        database.execute("UPDATE app_preferences SET appearance_mode=? WHERE id=1", (mode,))
    try:
        database.execute(
            "INSERT INTO sessions (id,name,created_at,finished_at,status) "
            "VALUES (7,'Estudo sintético',1000,1037,'finished')"
        )
        database.execute(
            "INSERT INTO study_intervals (id,session_id,started_at,last_seen_at,ended_at) "
            "VALUES (11,7,1000,1037,1037)"
        )
        database.execute(
            "INSERT INTO sessions (id,name,created_at,status) "
            "VALUES (8,'Recuperação sintética',2000,'paused')"
        )
        database.execute(
            "INSERT INTO study_intervals (id,session_id,started_at,last_seen_at) "
            "VALUES (12,8,2000,2003)"
        )
        database.execute("UPDATE sessions SET status='running' WHERE id=8")
        if origin == "v2":
            database.execute(
                "INSERT INTO study_types (id,name,name_key,color_key) "
                "VALUES (5,'Tipo sintético','tipo sintético','blue')"
            )
            database.execute("UPDATE sessions SET study_type_id=5")
    finally:
        database.close()


def _wait_ready(process: subprocess.Popen[bytes], profile: Path, log_offset: int) -> None:
    deadline = time.monotonic() + 20
    log_path = profile / "StudyTimer" / "logs" / "studytimer.log"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("O executável encerrou antes de concluir a inicialização.")
        if log_path.is_file():
            log = log_path.read_bytes()[log_offset:].decode("utf-8", errors="replace")
            assert "STARTUP_FAILED" not in log, "O pacote registrou falha de inicialização."
            if "APPLICATION_READY" in log:
                return
        time.sleep(0.05)  # Espera de prontidão, não uma prova de duração do relógio.
    raise AssertionError("O pacote não confirmou prontidão dentro do prazo.")


def _request_close(pid: int) -> None:
    """Endereça apenas as janelas visíveis pertencentes ao processo de teste."""
    # Fechar o diálogo cancela a recuperação; depois a janela principal salva/fecha.
    for hwnd in sorted(
        windows_for_pid(pid), key=lambda handle: window_title(handle) == "StudyTimer"
    ):
        close_window(hwnd)


def _close_process(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while process.poll() is None and time.monotonic() < deadline:
        _request_close(process.pid)
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass
    assert process.poll() is not None, "O pacote não fechou pela janela dentro do prazo."


def _open_and_close(executable: Path, profile: Path) -> None:
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(profile)
    log_path = profile / "StudyTimer" / "logs" / "studytimer.log"
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    process = subprocess.Popen([str(executable)], env=environment, cwd=profile)
    try:
        _wait_ready(process, profile, log_offset)
        assert (profile / "StudyTimer" / "estudos.db").is_file()
        _close_process(process)
        assert process.returncode == 0, "O pacote encerrou com erro."
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)


@pytest.mark.parametrize("origin", ["new", "v1", "v2"])
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_windows_bundle_opens_migrates_and_preserves_data(
    tmp_path: Path,
    origin: str,
    mode: str,
) -> None:
    bundle_dir = os.environ.get("STUDYTIMER_BUILD_DIR")
    if sys.platform != "win32" or not bundle_dir:
        pytest.skip("Requer build Windows e STUDYTIMER_BUILD_DIR definido.")
    bundle = Path(bundle_dir)
    executable = bundle / "StudyTimer.exe"
    assert executable.is_file()
    assert (bundle / "_internal" / "app" / "database" / "schema.sql").is_file()
    assert (bundle / "_internal" / "assets" / "studytimer.ico").is_file()
    assert (bundle / "_internal" / "customtkinter" / "assets").is_dir()
    database_path = tmp_path / "StudyTimer" / "estudos.db"
    _prepare_data(database_path, origin, mode)
    _open_and_close(executable, tmp_path)
    validate_database(database_path)
    database = sqlite3.connect(database_path, isolation_level=None)
    try:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 2
        assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        if origin != "new":
            assert database.execute(
                "SELECT id,name,status FROM sessions ORDER BY id"
            ).fetchall() == [
                (7, "Estudo sintético", "finished"),
                (8, "Recuperação sintética", "paused"),
            ]
            assert database.execute(
                "SELECT id,ended_at,last_seen_at FROM study_intervals ORDER BY id"
            ).fetchall() == [(11, 1037, 1037), (12, 2003, 2003)]
        else:
            assert database.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        if origin == "v2":
            assert database.execute("SELECT id,name,color_key FROM study_types").fetchall() == [
                (5, "Tipo sintético", "blue")
            ]
            assert database.execute("SELECT DISTINCT study_type_id FROM sessions").fetchall() == [
                (5,)
            ]
        else:
            assert database.execute("SELECT count(*) FROM study_types").fetchone()[0] == 0
        initial_mode = mode if origin == "v2" else "dark"
        assert (
            database.execute("SELECT appearance_mode FROM app_preferences").fetchone()[0]
            == initial_mode
        )
        database.execute("UPDATE app_preferences SET appearance_mode=? WHERE id=1", (mode,))
    finally:
        database.close()
    if origin == "v1":
        backups = list((database_path.parent / "backups" / "before-migration").glob("*.db"))
        assert len(backups) == 1
        backup = sqlite3.connect(backups[0])
        try:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
            assert (
                backup.execute("SELECT status FROM sessions WHERE id=8").fetchone()[0] == "running"
            )
        finally:
            backup.close()
    # Outra execução comprova leitura da preferência persistida e idempotência.
    _open_and_close(executable, tmp_path)
    database = sqlite3.connect(database_path)
    try:
        assert database.execute("SELECT appearance_mode FROM app_preferences").fetchone()[0] == mode
        assert database.execute("SELECT count(*) FROM sessions").fetchone()[0] == (
            0 if origin == "new" else 2
        )
    finally:
        database.close()
