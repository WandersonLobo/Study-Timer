"""Regressões de privacidade, validação, instância única e fronteira de SQL."""

import ast
import logging
import runpy
import socket
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import AppPaths
from app.database.connection import initialize_database
from app.single_instance import AlreadyRunningError, SingleInstance
from app.validation import normalize_session_name

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("  Matemática  ", "Matemática"),
        (" \n\t\x00", "Estudo livre"),
        ("A\x00\r\n\t\x1bB\u202e", "AB"),
        ("x" * 120, "x" * 120),
        ("Robert'); DROP TABLE sessions;--", "Robert'); DROP TABLE sessions;--"),
    ],
)
def test_session_name_normalization(name: str, expected: str) -> None:
    assert normalize_session_name(name) == expected


def test_session_name_over_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="120"):
        normalize_session_name("x" * 121)


def test_user_text_is_stored_only_as_parameter(connection: sqlite3.Connection) -> None:
    name = normalize_session_name("Robert'); DROP TABLE sessions;--")
    connection.execute(
        "INSERT INTO sessions (name, created_at, status) VALUES (?, ?, ?)",
        (name, 1000, "paused"),
    )
    assert connection.execute("SELECT name FROM sessions").fetchone()[0] == name


def test_production_sql_is_literal_or_versioned_schema() -> None:
    for path in (PROJECT_ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"execute", "executemany", "executescript"}:
                continue
            assert node.args, str(path)
            sql = node.args[0]
            if node.func.attr == "executescript":
                assert path.name == "connection.py" and isinstance(sql, ast.Name)
                assert sql.id == "schema"
            else:
                assert isinstance(sql, ast.Constant) and isinstance(sql.value, str), str(path)


@pytest.mark.skipif(sys.platform != "win32", reason="Lock de byte Windows.")
def test_instance_lock_blocks_second_handle_and_releases_after_error(tmp_path: Path) -> None:
    lock_path = tmp_path / "instance.lock"
    with pytest.raises(RuntimeError, match="simulada"), SingleInstance(lock_path):
        with pytest.raises(AlreadyRunningError), SingleInstance(lock_path):
            pytest.fail("Segunda instância adquiriu o lock.")
        raise RuntimeError("falha simulada")
    with SingleInstance(lock_path):
        assert lock_path.exists()


@pytest.mark.parametrize("relative", ["estudos.db", "nested/test.sqlite3", "logs/run.log", "a.csv"])
def test_bundle_check_rejects_private_files(tmp_path: Path, relative: str) -> None:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"private")
    checker = runpy.run_path(str(PROJECT_ROOT / "packaging" / "check_bundle.py"))["check_bundle"]
    with pytest.raises(ValueError, match="privado"):
        checker(tmp_path)


def test_bundle_check_rejects_private_path_split_between_blocks(tmp_path: Path) -> None:
    (tmp_path / "app.exe").write_bytes(b"x" * (1_048_576 - 2) + b"C:\\Users\\Private\\app.py")
    checker = runpy.run_path(str(PROJECT_ROOT / "packaging" / "check_bundle.py"))["check_bundle"]
    with pytest.raises(ValueError, match="caminho privado"):
        checker(tmp_path)


def test_bundle_check_accepts_resources_without_personal_data(tmp_path: Path) -> None:
    (tmp_path / "app.exe").write_bytes(b"MZ\x00\x00")
    (tmp_path / "schema.sql").write_text("CREATE TABLE test (id INTEGER);", encoding="utf-8")
    checker = runpy.run_path(str(PROJECT_ROOT / "packaging" / "check_bundle.py"))["check_bundle"]
    checker(tmp_path)


def test_bundle_check_rejects_database_with_innocent_extension(tmp_path: Path) -> None:
    (tmp_path / "asset.dat").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    checker = runpy.run_path(str(PROJECT_ROOT / "packaging" / "check_bundle.py"))["check_bundle"]
    with pytest.raises(ValueError, match="renomeado"):
        checker(tmp_path)


def test_bundle_check_rejects_private_path_encoded_as_utf16(tmp_path: Path) -> None:
    (tmp_path / "app.exe").write_bytes(r"C:\Users\Private\app.py".encode("utf-16-le"))
    checker = runpy.run_path(str(PROJECT_ROOT / "packaging" / "check_bundle.py"))["check_bundle"]
    with pytest.raises(ValueError, match="caminho privado"):
        checker(tmp_path)


def test_infrastructure_initializes_with_network_unavailable(tmp_path: Path) -> None:
    with patch.object(socket, "socket", side_effect=AssertionError("Rede indisponível")):
        database = initialize_database(tmp_path / "offline.db")
        database.close()
    # Este teste cobre infraestrutura; não substitui o teste do exe com firewall.


def test_startup_failure_hides_paths_and_session_text(caplog: pytest.LogCaptureFixture) -> None:
    import main

    private_text = r"C:\Users\NomePrivado\Concurso X"
    with (
        patch.object(AppPaths, "from_environment", side_effect=OSError(private_text)),
        patch.object(main, "show_startup_message") as dialog,
        patch.object(logging.getLogger("studytimer"), "propagate", True),
        caplog.at_level(logging.ERROR, logger="studytimer"),
    ):
        main.main()
    dialog.assert_called_once()
    assert private_text not in str(dialog.call_args)
    assert private_text not in caplog.text
    assert "STARTUP_FAILED type=OSError" in caplog.text
