"""Verifica a infraestrutura de primeira execução sem carregar a interface."""

import logging
from pathlib import Path

import pytest

from app.config import AppPaths
from app.logging_config import configure_logging


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
