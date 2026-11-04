"""Verificações de integridade sem reparar nem sobrescrever o banco original."""

import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.database.schema_version import CURRENT_SCHEMA_VERSIONS, SUPPORTED_SCHEMA_VERSIONS


class DatabaseHealthError(RuntimeError):
    """Indica corrupção física ou referências SQLite inválidas."""


class DatabaseVersionError(RuntimeError):
    """Indica um banco de outra versão, que exige migração explícita."""


def validate_integrity(connection: sqlite3.Connection) -> None:
    """Exige integridade física e chaves estrangeiras, sem interpretar versões."""
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    if len(rows) != 1 or rows[0][0] != "ok":
        raise DatabaseHealthError("O banco não passou na verificação de integridade.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise DatabaseHealthError("O banco contém referências inválidas.")


def validate_connection(
    connection: sqlite3.Connection,
    *,
    supported_versions: frozenset[int] = CURRENT_SCHEMA_VERSIONS,
) -> None:
    """Valida integridade e versão; o padrão exige o esquema atual.

    Abertura anterior à migração e backups antigos aceitam explicitamente v1/v2.
    Nenhum caminho permite versões desconhecidas ou desliga a validação.
    """
    if not supported_versions or not supported_versions <= SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError("Política de versões não suportada.")
    validate_integrity(connection)
    if connection.execute("PRAGMA user_version").fetchone()[0] not in supported_versions:
        raise DatabaseVersionError("Versão de banco incompatível; migração necessária.")


def validate_database(
    database_path: Path,
    *,
    supported_versions: frozenset[int] = CURRENT_SCHEMA_VERSIONS,
) -> None:
    """Valida um arquivo existente em conexão somente de leitura.

    Args:
        database_path: Banco ou backup a verificar antes de abrir ou restaurar.
    """
    uri = database_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA trusted_schema = OFF")
        validate_connection(connection, supported_versions=supported_versions)
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
