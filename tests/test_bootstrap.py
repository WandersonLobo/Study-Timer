"""Verifica a infraestrutura de primeira execução sem carregar a interface."""

import logging
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.config import AppPaths
from app.database.connection import initialize_database
from app.database.repository import StudyRepository
from app.logging_config import configure_logging
from app.models import ClockSnapshot, SessionStatus
from app.services.report_service import ReportService
from app.services.timer_service import TimerService


def test_paths_and_logs_use_local_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = AppPaths.from_environment()
    paths.ensure_directories()
    assert paths.database == tmp_path / "StudyTimer" / "estudos.db"
    configure_logging(paths.log_file)
    logger = logging.getLogger("studytimer")
    try:
        logger.info("Inicialização de infraestrutura")
        assert "Inicialização de infraestrutura" in paths.log_file.read_text(encoding="utf-8")
    finally:
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


def test_missing_local_app_data_has_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(RuntimeError, match="LOCALAPPDATA"):
        AppPaths.from_environment()


def test_application_composition_recovers_before_creating_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import main

    paths = AppPaths(tmp_path)
    paths.ensure_directories()
    database = initialize_database(paths.database)
    try:
        repository = StudyRepository(database)
        session, interval = repository.start_session("Inicialização após interrupção", 1000)
        repository.save_checkpoint(session.id, ClockSnapshot(interval.id, 1000, 5, 1005))
    finally:
        database.close()
    events: list[str] = []

    class StubApplication:
        def __init__(self, timer: TimerService, reports: ReportService) -> None:
            active = timer.get_active_session()
            assert active is not None and active.id == session.id
            assert active.status == SessionStatus.PAUSED
            assert not timer.persistence_failed
            events.append("window")

        def mainloop(self) -> None:
            events.append("mainloop")

    module = ModuleType("app.application")
    module.__dict__["Application"] = StubApplication
    monkeypatch.setitem(sys.modules, "app.application", module)
    main.run_application(paths)
    assert events == ["window", "mainloop"]
