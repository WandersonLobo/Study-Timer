"""Migração explícita e atômica de v1 para v2; backup pertence ao chamador."""

import sqlite3

from app.database.health import validate_connection
from app.database.repository import StudyRepository
from app.database.schema_version import SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS


def migrate_database(connection: sqlite3.Connection) -> None:
    """Atualiza uma conexão já validada e protegida por backup/lock.

    A preparação de restauração usa uma cópia SQLite, preservando a origem.
    DDL e user_version são confirmados juntos, sem executescript implícito.
    """
    if connection.in_transaction:
        raise ValueError("Migração exige conexão sem transação aberta.")
    validate_connection(connection, supported_versions=SUPPORTED_SCHEMA_VERSIONS)
    if connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
        return
    with StudyRepository(connection).transaction() as database:
        database.execute(
            """
            CREATE TABLE study_types (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 60),
                name_key TEXT NOT NULL UNIQUE
                    CHECK (length(name_key) > 0 AND name_key != 'sem tipo'),
                color_key TEXT NOT NULL CHECK (
                    color_key IN ('blue', 'teal', 'orange', 'purple', 'rose', 'cyan',
                                  'amber', 'slate')
                ),
                is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1))
            )
            """
        )
        database.execute(
            """
            CREATE TABLE app_preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                appearance_mode TEXT NOT NULL CHECK (appearance_mode IN ('light', 'dark'))
            )
            """
        )
        database.execute("INSERT INTO app_preferences (id, appearance_mode) VALUES (1, 'dark')")
        database.execute(
            "ALTER TABLE sessions ADD COLUMN study_type_id INTEGER REFERENCES study_types(id)"
        )
        database.execute("CREATE INDEX ix_sessions_study_type ON sessions(study_type_id)")
        database.execute("PRAGMA user_version = 2")
        validate_connection(database)
