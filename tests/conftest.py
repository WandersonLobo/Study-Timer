"""Fixtures isoladas: testes nunca escrevem no banco real do usuário."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.database.connection import initialize_database


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """Abre um banco temporário com o mesmo esquema e PRAGMAs da aplicação."""
    database = initialize_database(tmp_path / "estudos.db")
    try:
        yield database
    finally:
        database.close()
