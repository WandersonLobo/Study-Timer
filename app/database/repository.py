"""Centraliza SQL e valida invariantes cruzadas antes do COMMIT."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.models import Session, SessionStatus


class StudyRepository:
    """Fornece a fronteira de persistência para os serviços, sem widgets."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Abre uma escrita atômica e valida o estado final antes de confirmar.

        Returns:
            Contexto com a conexão para operações parametrizadas.

        Raises:
            sqlite3.Error: Em falha de escrita ou violação de invariantes.
        """
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
            self.validate_invariants()
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def validate_invariants(self) -> None:
        """Rejeita combinações inválidas de estados e intervalos abertos."""
        invalid = self._connection.execute(
            """
            SELECT s.id FROM sessions AS s
            LEFT JOIN study_intervals AS i
                ON i.session_id = s.id AND i.ended_at IS NULL
            GROUP BY s.id
            HAVING (s.status = 'running' AND count(i.id) != 1)
                OR (s.status != 'running' AND count(i.id) != 0)
            LIMIT 1
            """
        ).fetchone()
        if invalid is not None:
            raise sqlite3.IntegrityError("Estado da sessão incompatível com intervalos abertos.")
        if self._connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("Referência de sessão inválida.")

    def get_pending_session(self) -> Session | None:
        """Consulta a única sessão pendente sem alterar a recuperação."""
        row = self._connection.execute(
            "SELECT id, name, created_at, finished_at, status FROM sessions WHERE status IN (?, ?)",
            (SessionStatus.RUNNING.value, SessionStatus.PAUSED.value),
        ).fetchone()
        if row is None:
            return None
        return Session(
            id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            status=SessionStatus(row["status"]),
        )
