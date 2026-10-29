"""Backups SQLite consistentes, com validação e retenção local limitada."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.database.health import validate_connection, validate_database
from app.single_instance import SingleInstance


def create_backup(connection: sqlite3.Connection, backup_dir: Path, keep: int = 5) -> Path:
    """Cria um snapshot validado pela API SQLite antes de remover cópias antigas.

    Args:
        connection: Conexão de origem sem transação aberta.
        backup_dir: Diretório privado que recebe as cópias sem criptografia.
        keep: Quantidade de backups automáticos a preservar, no mínimo um.

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
        connection.backup(target)
        validate_connection(target)
    finally:
        target.close()
    # Somente uma cópia completa e validada entra na rotação.
    temporary.replace(destination)
    backups = sorted(
        (path for path in backup_dir.glob("studytimer-*.db") if path != destination), reverse=True
    )
    # O backup recém-criado deve sobreviver mesmo se o relógio civil retroceder.
    for old_backup in backups[keep - 1 :]:
        old_backup.unlink()
    return destination


def restore_backup(backup_path: Path, database_path: Path) -> None:
    """Restaura via API SQLite após validar o backup e proteger a versão atual.

    Obtém o mesmo lock exclusivo da inicialização; o aplicativo deve estar fechado.
    A origem nunca é copiada diretamente sobre o arquivo SQLite em uso.
    """
    validate_database(backup_path)
    if backup_path.resolve() == database_path.resolve():
        raise ValueError("Backup e banco de destino devem ser diferentes.")
    with SingleInstance(database_path.parent / "instance.lock"):
        _restore_validated_backup(backup_path, database_path)


def _restore_validated_backup(backup_path: Path, database_path: Path) -> None:
    """Preserva a versão atual e restaura mantendo o lock exclusivo no chamador."""
    if database_path.exists():
        validate_database(database_path)
    source = sqlite3.connect(backup_path.resolve().as_uri() + "?mode=ro", uri=True)
    destination = sqlite3.connect(database_path)
    try:
        if database_path.exists():
            # Um banco recém-criado ainda não possui schema para ser copiado.
            if destination.execute("PRAGMA user_version").fetchone()[0] != 0:
                # A retenção da cópia de segurança não pode excluir a origem da restauração.
                create_backup(destination, database_path.parent / "backups" / "before-restore")
        source.backup(destination)
        validate_connection(destination)
    finally:
        destination.close()
        source.close()
