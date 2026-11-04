"""Backups SQLite consistentes, com validação e retenção local limitada."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.database.health import validate_connection, validate_database
from app.database.migrations import migrate_database
from app.database.repository import StudyRepository
from app.database.schema_version import CURRENT_SCHEMA_VERSIONS, SUPPORTED_SCHEMA_VERSIONS
from app.single_instance import SingleInstance


def create_backup(
    connection: sqlite3.Connection,
    backup_dir: Path,
    keep: int = 5,
    *,
    supported_versions: frozenset[int] = CURRENT_SCHEMA_VERSIONS,
    preserve_path: Path | None = None,
) -> Path:
    """Cria um snapshot validado pela API SQLite antes de remover cópias antigas.

    Args:
        connection: Conexão de origem sem transação aberta.
        backup_dir: Diretório privado que recebe as cópias sem criptografia.
        keep: Retenção desejada, no mínimo um; novo snapshot e origem protegida
            têm prioridade mesmo quando juntos ultrapassam esse limite.
        supported_versions: Versões conhecidas aceitas; v1 só nos caminhos de atualização.
        preserve_path: Origem de restauração que não pode ser removida pela rotação.

    Returns:
        Caminho do novo backup confirmado e fechado.
    """
    if keep < 1 or connection.in_transaction:
        raise ValueError("Backup exige retenção positiva e nenhuma transação aberta.")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_dir / f"studytimer-{stamp}-{uuid4().hex}.db"
    temporary = destination.with_suffix(".pending")
    target = sqlite3.connect(temporary)
    try:
        try:
            connection.backup(target)
            validate_connection(target, supported_versions=supported_versions)
        finally:
            target.close()
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    # Somente uma cópia completa e validada entra na rotação.
    temporary.replace(destination)
    backups = sorted(
        (path for path in backup_dir.glob("studytimer-*.db") if path != destination), reverse=True
    )
    # Ambos sobrevivem mesmo se o relógio civil retroceder ou a origem for antiga.
    preserved = preserve_path.resolve() if preserve_path is not None else None
    protected = [path for path in backups if path.resolve() == preserved]
    disposable = [path for path in backups if path.resolve() != preserved]
    available = max(0, keep - 1 - len(protected))
    for old_backup in disposable[available:]:
        old_backup.unlink()
    return destination


def restore_backup(backup_path: Path, database_path: Path) -> None:
    """Restaura via API SQLite após validar o backup e proteger a versão atual.

    Obtém o mesmo lock exclusivo da inicialização; o aplicativo deve estar fechado.
    A origem nunca é copiada diretamente sobre o arquivo SQLite em uso.
    """
    if backup_path.resolve() == database_path.resolve():
        raise ValueError("Backup e banco de destino devem ser diferentes.")
    validate_database(backup_path, supported_versions=SUPPORTED_SCHEMA_VERSIONS)
    with SingleInstance(database_path.parent / "instance.lock"):
        _restore_validated_backup(backup_path, database_path)


def _restore_validated_backup(backup_path: Path, database_path: Path) -> None:
    """Prepara v2 antes de tocar o destino; exige o lock exclusivo no chamador."""
    if backup_path.resolve() == database_path.resolve():
        raise ValueError("Backup e banco de destino devem ser diferentes.")
    with TemporaryDirectory(prefix=".restore-", dir=database_path.parent) as directory:
        prepared = sqlite3.connect(Path(directory) / "prepared.db", isolation_level=None)
        try:
            source = sqlite3.connect(backup_path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                source.execute("PRAGMA trusted_schema = OFF")
                validate_connection(source, supported_versions=SUPPORTED_SCHEMA_VERSIONS)
                source.backup(prepared)
            finally:
                source.close()
            prepared.row_factory = sqlite3.Row
            prepared.execute("PRAGMA foreign_keys = ON")
            prepared.execute("PRAGMA trusted_schema = OFF")
            prepared.execute("PRAGMA busy_timeout = 5000")
            prepared.execute("PRAGMA synchronous = FULL")
            migrate_database(prepared)
            validate_connection(prepared)
            StudyRepository(prepared).validate_invariants()
            existing = database_path.exists()
            if existing:
                validate_database(database_path, supported_versions=SUPPORTED_SCHEMA_VERSIONS)
            destination = sqlite3.connect(database_path, isolation_level=None)
            try:
                destination.execute("PRAGMA foreign_keys = ON")
                destination.execute("PRAGMA trusted_schema = OFF")
                destination.execute("PRAGMA busy_timeout = 5000")
                mode = destination.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                if str(mode).lower() != "wal":
                    raise RuntimeError("Não foi possível confirmar journal_mode=WAL.")
                destination.execute("PRAGMA synchronous = FULL")
                if existing:
                    create_backup(
                        destination,
                        database_path.parent / "backups" / "before-restore",
                        supported_versions=SUPPORTED_SCHEMA_VERSIONS,
                        preserve_path=backup_path,
                    )
                prepared.backup(destination)
                validate_connection(destination)
            finally:
                destination.close()
        finally:
            prepared.close()
