"""Abre conexões SQLite e inicializa o esquema versionado da aplicação."""

import sqlite3
from pathlib import Path

from app.database.backup import create_backup
from app.database.health import (
    DatabaseHealthError,
    preserve_corrupt_database,
    validate_connection,
    validate_database,
)
from app.database.migrations import migrate_database
from app.database.schema_version import SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS


def initialize_database(database_path: Path) -> sqlite3.Connection:
    """Cria ou abre o banco e aplica os PRAGMAs exigidos.

    Args:
        database_path: Caminho do banco em um diretório previamente criado.

    Returns:
        Conexão em modo explícito de transações, pertencente ao chamador.

    Raises:
        sqlite3.Error: Se houver falha de leitura, escrita ou esquema.
        RuntimeError: Se WAL não for confirmado ou o schema for incompatível.
    """
    existing = database_path.exists()
    if existing:
        try:
            validate_database(database_path, supported_versions=SUPPORTED_SCHEMA_VERSIONS)
        except sqlite3.DatabaseError as error:
            if error.sqlite_errorcode & 0xFF not in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                raise
            preserve_corrupt_database(database_path)
            raise DatabaseHealthError("Banco inválido; cópia de diagnóstico preservada.") from None
        except DatabaseHealthError:
            preserve_corrupt_database(database_path)
            raise DatabaseHealthError("Banco inválido; cópia de diagnóstico preservada.") from None
    connection = sqlite3.connect(database_path, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA trusted_schema = OFF")
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError("Não foi possível confirmar journal_mode=WAL.")
        connection.execute("PRAGMA synchronous = FULL")
        if not existing:
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            connection.executescript(schema)
        elif connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            create_backup(
                connection,
                database_path.parent / "backups" / "before-migration",
                supported_versions=SUPPORTED_SCHEMA_VERSIONS,
            )
            migrate_database(connection)
        validate_connection(connection)
        if existing:
            create_backup(connection, database_path.parent / "backups")
        return connection
    except (sqlite3.Error, OSError, RuntimeError):
        connection.close()
        raise
