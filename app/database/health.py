"""Verificações de integridade sem reparar nem sobrescrever o banco original."""

import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 1


class DatabaseHealthError(RuntimeError):
    """Indica corrupção física ou referências SQLite inválidas."""


class DatabaseVersionError(RuntimeError):
    """Indica um banco de outra versão, que exige migração explícita."""


def validate_connection(connection: sqlite3.Connection) -> None:
    """Exige integridade física, chaves estrangeiras e versão reconhecida."""
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    if len(rows) != 1 or rows[0][0] != "ok":
        raise DatabaseHealthError("O banco não passou na verificação de integridade.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise DatabaseHealthError("O banco contém referências inválidas.")
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise DatabaseVersionError("Versão de banco incompatível; migração necessária.")


def validate_database(database_path: Path) -> None:
    """Valida um arquivo existente em conexão somente de leitura.

    Args:
        database_path: Banco ou backup a verificar antes de abrir ou restaurar.
    """
    uri = database_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA trusted_schema = OFF")
        validate_connection(connection)
    finally:
        connection.close()


def preserve_corrupt_database(database_path: Path) -> None:
    """Preserva uma cópia bruta do banco e sidecars para análise manual.

    A aplicação deve estar sob seu lock exclusivo. Não há tentativa de reparo,
    remoção ou substituição dos arquivos originais. As cópias continuam privadas.
    """
    suffix = "." + uuid4().hex + ".corrupt"
    for sidecar in ("", "-wal", "-shm", "-journal"):
        source = Path(str(database_path) + sidecar)
        if source.is_file():
            shutil.copy2(source, source.with_name(source.name + suffix))
