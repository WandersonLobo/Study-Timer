"""Jornadas externas do EXE real; sem acesso aos objetos ou comandos do aplicativo.

Entrada depende de desktop Windows desbloqueado. O opt-in ausente permite rodar
pytest localmente; na CI obrigatória, o preflight e o gate rejeitam skips.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tests.windows_input import (
    Desktop,
    close_window,
    find_window,
    wait_until,
    window_title,
    windows_for_pid,
)

pytestmark = [pytest.mark.build, pytest.mark.desktop_ui]

TAB, ENTER, ESCAPE, UP, DOWN = 0x09, 0x0D, 0x1B, 0x26, 0x28


@pytest.fixture
def packaged_executable() -> Path:
    if os.environ.get("STUDYTIMER_DESKTOP_E2E") != "1":
        pytest.skip("Requer opt-in STUDYTIMER_DESKTOP_E2E=1 e desktop interativo.")
    assert sys.platform == "win32", "A jornada externa exige Windows."
    directory = os.environ.get("STUDYTIMER_BUILD_DIR")
    assert directory, "O opt-in exige STUDYTIMER_BUILD_DIR."
    executable = Path(directory) / "StudyTimer.exe"
    assert executable.is_file(), "O executável do pacote não foi encontrado."
    return executable


def _database(profile: Path) -> Path:
    return profile / "StudyTimer" / "estudos.db"


def _rows(profile: Path, sql: str) -> list[tuple[Any, ...]]:
    # Observação somente leitura: o usuário continua comandando tudo pela UI.
    connection = sqlite3.connect(_database(profile).as_uri() + "?mode=ro", uri=True)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _prepare_profile(profile: Path, mode: str) -> None:
    """Fixture sintética fechada antes de iniciar o processo, sem dados pessoais."""
    path = _database(profile)
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    try:
        schema = Path(__file__).parents[1] / "app" / "database" / "schema.sql"
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.execute("UPDATE app_preferences SET appearance_mode=? WHERE id=1", (mode,))
        connection.commit()
    finally:
        connection.close()


def _evidence(profile: Path, name: str, hwnd: int, pid: int) -> None:
    destination = Path(os.environ.get("STUDYTIMER_EVIDENCE_DIR", str(profile / "evidence")))
    # PrintWindow pode aguardar uma janela travada: limitar o capturador por
    # subprocesso mantém o prazo do teste e libera seus recursos pelo Windows.
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.capture_native_window",
            str(pid),
            str(hwnd),
            str(destination / f"{name}.png"),
        ],
        cwd=Path(__file__).parents[1],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.communicate(timeout=20)
    except BaseException as error:
        try:
            # Na venv, python.exe pode ser um redirector com outro processo
            # filho. Encerrar só o lançador deixaria PrintWindow bloqueado.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            process.communicate(timeout=5)
        except (OSError, subprocess.SubprocessError) as cleanup_error:
            error.add_note(f"Falha ao encerrar capturador: {type(cleanup_error).__name__}.")
        if isinstance(error, subprocess.TimeoutExpired):
            raise RuntimeError("Prazo de captura da janela sintética excedido.") from None
        raise
    if process.returncode:
        raise RuntimeError("Não foi possível capturar a janela sintética de teste.")


def _close(process: subprocess.Popen[bytes]) -> None:
    def closed() -> bool:
        for hwnd in sorted(
            windows_for_pid(process.pid), key=lambda item: window_title(item) == "StudyTimer"
        ):
            close_window(hwnd)
        return process.poll() is not None

    wait_until(closed, timeout=10, message="O processo não concluiu o fechamento pela janela.")
    assert process.wait(timeout=5) == 0, "O executável terminou com erro."


@contextmanager
def _running(executable: Path, profile: Path, scenario: str) -> Iterator[tuple[Desktop, int]]:
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(profile)
    log_path = profile / "StudyTimer" / "logs" / "studytimer.log"
    offset = log_path.stat().st_size if log_path.exists() else 0
    process = subprocess.Popen([str(executable)], env=environment, cwd=profile)
    hwnd = 0
    try:
        hwnd = find_window(process.pid)

        def ready() -> bool:
            if process.poll() is not None:
                raise AssertionError("O executável encerrou antes da prontidão da interface.")
            if not log_path.is_file():
                return False
            log = log_path.read_bytes()[offset:]
            assert b"STARTUP_FAILED" not in log, "O executável registrou falha de inicialização."
            return b"APPLICATION_READY" in log

        wait_until(ready, timeout=15, message="A interface não confirmou prontidão nesta execução.")
        desktop = Desktop(process.pid)
        # Uma recuperação modal pode estar aberta antes da janela ser achada;
        # ajustar a geometria não deve roubar o foco do diálogo real.
        desktop.size(hwnd, focus=False)
        yield desktop, hwnd
        _close(process)
    except BaseException as error:
        if hwnd and hwnd in windows_for_pid(process.pid):
            try:
                _evidence(profile, f"{scenario}-failure", hwnd, process.pid)
            except (OSError, RuntimeError, subprocess.SubprocessError) as capture_error:
                error.add_note(
                    f"Captura de diagnóstico indisponível: {type(capture_error).__name__}."
                )
        raise
    finally:
        if process.poll() is None:
            # Termina apenas a árvore que este teste criou; nunca busca por nome.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=10,
            )
        process.wait(timeout=10)


def _wait_status(profile: Path, status: str) -> None:
    wait_until(
        lambda: _rows(profile, "SELECT status FROM sessions") == [(status,)],
        message="A ação na interface não confirmou o estado esperado da sessão.",
    )


def _create_and_start(desktop: Desktop, hwnd: int, profile: Path) -> None:
    desktop.click(hwnd, 0.865, 0.35)
    dialog = find_window(desktop.pid, "Novo tipo")
    desktop.click(dialog, 0.50, 0.19)
    desktop.type_text("POO")
    desktop.key(ENTER)  # O formulário público salva por Enter no campo Nome.
    wait_until(
        lambda: _rows(profile, "SELECT name FROM study_types") == [("POO",)],
        message="O novo tipo não foi gravado pela interface.",
    )
    wait_until(lambda: dialog not in windows_for_pid(desktop.pid))
    desktop.click(hwnd, 0.60, 0.535)
    desktop.type_text("Encapsulamento sintético")
    # Partindo do Entry, a cadeia é Gerenciar -> Novo tipo -> seletor.
    for _ in range(3):
        desktop.key(TAB, shift=True)
    desktop.key(UP)
    desktop.key(DOWN)
    desktop.click(hwnd, 0.45, 0.805)
    _wait_status(profile, "running")
    assert _rows(
        profile,
        "SELECT sessions.name,study_types.name FROM sessions "
        "JOIN study_types ON study_types.id=sessions.study_type_id",
    ) == [("Encapsulamento sintético", "POO")]
    # O heartbeat fornece uma condição observável; não se pressupõe que um
    # sleep específico corresponda à duração calculada pelo relógio.
    wait_until(
        lambda: _database(profile).with_name("recovery-point.pending").is_file(),
        timeout=15,
        message="Não foi observado checkpoint de duração positiva.",
    )


def _assert_persisted(profile: Path, intervals: int) -> None:
    assert _rows(profile, "PRAGMA integrity_check") == [("ok",)]
    assert _rows(profile, "PRAGMA foreign_key_check") == []
    assert _rows(profile, "PRAGMA user_version") == [(2,)]
    assert _rows(profile, "SELECT status FROM sessions") == [("finished",)]
    assert _rows(profile, "SELECT count(*) FROM study_intervals") == [(intervals,)]
    assert _rows(profile, "SELECT 1 FROM study_intervals WHERE ended_at IS NULL") == []
    assert (
        _rows(
            profile,
            "SELECT 1 FROM study_intervals WHERE started_at>last_seen_at OR last_seen_at>ended_at",
        )
        == []
    )
    total = _rows(profile, "SELECT sum(ended_at-started_at) FROM study_intervals")[0][0]
    assert isinstance(total, int) and total > 0
    # Pausas e a reabertura são lacunas válidas entre intervalos; o término
    # corresponde ao último intervalo e não à soma das durações estudadas.
    last_end = _rows(profile, "SELECT max(ended_at) FROM study_intervals")[0][0]
    assert _rows(profile, "SELECT finished_at FROM sessions") == [(last_end,)]
    assert _rows(
        profile,
        "SELECT sessions.name,study_types.name FROM sessions "
        "JOIN study_types ON study_types.id=sessions.study_type_id",
    ) == [("Encapsulamento sintético", "POO")]


def _history(desktop: Desktop, hwnd: int, profile: Path, scenario: str, mode: str) -> None:
    desktop.click(hwnd, 0.11, 0.29)
    # O preenchimento fora das letras permite observar qual botão está ativo,
    # sem OCR, screenshots do desktop ou introspecção de objetos Python.
    primary = (22, 119, 255) if mode == "light" else (31, 106, 165)
    for label, center, probe in (
        ("day", 0.755, 0.728),
        ("week", 0.84, 0.812),
        ("month", 0.922, 0.895),
    ):
        desktop.click(hwnd, center, 0.09)
        desktop.click(hwnd, 0.98, 0.98)  # Retira hover do botão observado.

        def selected(x: float = probe) -> bool:
            return desktop.pixel(hwnd, x, 0.09) == primary

        wait_until(
            selected,
            message="O Histórico não confirmou visualmente o período selecionado.",
        )
        _evidence(profile, f"{scenario}-{label}", hwnd, desktop.pid)


def _switch_theme(desktop: Desktop, hwnd: int, profile: Path, mode: str) -> str:
    desktop.click(hwnd, 0.11, 0.215)
    next_mode = "dark" if mode == "light" else "light"
    desktop.choose_menu(hwnd, 0.11, 0.922, 1 if next_mode == "dark" else 0)
    wait_until(
        lambda: _rows(profile, "SELECT appearance_mode FROM app_preferences") == [(next_mode,)],
        message="A alteração de aparência pela interface não foi persistida.",
    )
    return next_mode


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_packaged_user_cycle(packaged_executable: Path, tmp_path: Path, mode: str) -> None:
    _prepare_profile(tmp_path, mode)
    scenario = f"cycle-{mode}"
    with _running(packaged_executable, tmp_path, scenario) as (desktop, hwnd):
        _create_and_start(desktop, hwnd, tmp_path)
        desktop.click(hwnd, 0.11, 0.29)
        _wait_status(tmp_path, "running")
        _evidence(tmp_path, f"{scenario}-history-running", hwnd, desktop.pid)
        desktop.click(hwnd, 0.11, 0.215)
        desktop.click(hwnd, 0.61, 0.805)
        _wait_status(tmp_path, "paused")
        _evidence(tmp_path, f"{scenario}-paused", hwnd, desktop.pid)
        desktop.click(hwnd, 0.45, 0.805)
        _wait_status(tmp_path, "running")
        desktop.click(hwnd, 0.76, 0.805)
        _wait_status(tmp_path, "finished")
        _history(desktop, hwnd, tmp_path, scenario, mode)
        next_mode = _switch_theme(desktop, hwnd, tmp_path, mode)
        _evidence(tmp_path, f"{scenario}-theme", hwnd, desktop.pid)
    _assert_persisted(tmp_path, intervals=2)
    with _running(packaged_executable, tmp_path, f"{scenario}-reopen") as (desktop, hwnd):
        assert _rows(tmp_path, "SELECT appearance_mode FROM app_preferences") == [(next_mode,)]
        _history(desktop, hwnd, tmp_path, f"{scenario}-reopen", next_mode)
    _assert_persisted(tmp_path, intervals=2)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_packaged_recovery(packaged_executable: Path, tmp_path: Path, mode: str) -> None:
    _prepare_profile(tmp_path, mode)
    scenario = f"recovery-{mode}"
    with _running(packaged_executable, tmp_path, scenario) as (desktop, hwnd):
        _create_and_start(desktop, hwnd, tmp_path)
        _evidence(tmp_path, f"{scenario}-running", hwnd, desktop.pid)
        # A saída normal durante contagem salva a sessão pendente como pausada.
    _wait_status(tmp_path, "paused")
    frozen = _rows(tmp_path, "SELECT started_at,last_seen_at,ended_at FROM study_intervals")
    with _running(packaged_executable, tmp_path, f"{scenario}-reopen") as (desktop, hwnd):
        dialog = find_window(desktop.pid, "Sessão recuperada")
        _evidence(tmp_path, f"{scenario}-dialog", dialog, desktop.pid)
        desktop.focus(dialog)
        desktop.key(ESCAPE)  # Cancelar mantém a recuperação pausada.
        wait_until(lambda: dialog not in windows_for_pid(desktop.pid))
        _wait_status(tmp_path, "paused")
        assert (
            _rows(tmp_path, "SELECT started_at,last_seen_at,ended_at FROM study_intervals")
            == frozen
        )
        desktop.click(hwnd, 0.45, 0.805)
        _wait_status(tmp_path, "running")
        desktop.click(hwnd, 0.76, 0.805)
        _wait_status(tmp_path, "finished")
        _evidence(tmp_path, f"{scenario}-finished", hwnd, desktop.pid)
    _assert_persisted(tmp_path, intervals=2)
