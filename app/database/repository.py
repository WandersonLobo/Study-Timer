"""Centraliza SQL e valida invariantes cruzadas antes do COMMIT."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.models import ClockSnapshot, Session, SessionStatus, StudyInterval
from app.validation import normalize_session_name


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
        return self._session_from_row(row)

    def get_session(self, session_id: int) -> Session | None:
        """Consulta uma sessão pelo identificador, inclusive após sua finalização."""
        row = self._connection.execute(
            "SELECT id, name, created_at, finished_at, status FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return None if row is None else self._session_from_row(row)

    def get_open_interval(self, session_id: int) -> StudyInterval | None:
        """Consulta o único intervalo aberto da sessão sem alterar seu checkpoint."""
        row = self._connection.execute(
            "SELECT id, session_id, started_at, last_seen_at, ended_at "
            "FROM study_intervals WHERE session_id = ? AND ended_at IS NULL",
            (session_id,),
        ).fetchone()
        return None if row is None else self._interval_from_row(row)

    def get_session_intervals(self, session_id: int) -> list[StudyInterval]:
        """Lista intervalos por ordem de criação, mesmo após correção do relógio civil."""
        rows = self._connection.execute(
            "SELECT id, session_id, started_at, last_seen_at, ended_at "
            "FROM study_intervals WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [self._interval_from_row(row) for row in rows]

    def start_session(self, name: str, started_at: int) -> tuple[Session, StudyInterval]:
        """Cria sessão e primeiro intervalo em uma única transação.

        Args:
            name: Nome a normalizar e validar antes da escrita.
            started_at: Âncora UTC inteira capturada pelo relógio.

        Returns:
            Sessão running e intervalo aberto, somente após COMMIT.

        Raises:
            RuntimeError: Se já houver sessão pendente.
            ValueError: Se o nome for inválido.
            sqlite3.Error: Se a transação não puder ser confirmada.
        """
        name = normalize_session_name(name)
        with self.transaction() as database:
            if self.get_pending_session() is not None:
                raise RuntimeError("Já existe uma sessão pendente.")
            cursor = database.execute(
                "INSERT INTO sessions (name, created_at, status) VALUES (?, ?, ?)",
                (name, started_at, SessionStatus.PAUSED.value),
            )
            session_id = cursor.lastrowid
            assert session_id is not None
            interval = self._open_interval(session_id, started_at)
            session = self._require_session(session_id, SessionStatus.RUNNING)
        return session, interval

    def resume_session(self, session_id: int, started_at: int) -> tuple[Session, StudyInterval]:
        """Retoma uma sessão paused criando um novo intervalo atomicamente."""
        with self.transaction():
            self._require_session(session_id, SessionStatus.PAUSED)
            interval = self._open_interval(session_id, started_at)
            session = self._require_session(session_id, SessionStatus.RUNNING)
        return session, interval

    def pause_session(self, session_id: int, snapshot: ClockSnapshot) -> Session:
        """Fecha o intervalo no snapshot validado e muda running para paused.

        Raises:
            RuntimeError: Se a sessão não estiver running.
            ValueError: Se o snapshot não corresponder ao intervalo ou regredir o checkpoint.
            sqlite3.Error: Se houver falha, com rollback integral da operação.
        """
        with self.transaction() as database:
            self._require_session(session_id, SessionStatus.RUNNING)
            self._close_interval(session_id, snapshot)
            database.execute(
                "UPDATE sessions SET status = ? WHERE id = ?",
                (SessionStatus.PAUSED.value, session_id),
            )
            session = self._require_session(session_id, SessionStatus.PAUSED)
        return session

    def finish_session(self, session_id: int, snapshot: ClockSnapshot | None = None) -> Session:
        """Finaliza uma sessão pendente preservando o maior término confirmado.

        Args:
            session_id: Sessão running ou paused a concluir.
            snapshot: Obrigatório para running; deve ser None para paused.

        Returns:
            Sessão finished. Se todos os intervalos tiverem zero segundos,
            finished_at será created_at; caso contrário, o maior término ou created_at.

        Raises:
            RuntimeError: Se não houver sessão pendente correspondente.
            ValueError: Se faltar snapshot ou ele não corresponder ao estado persistido.
            sqlite3.Error: Se qualquer etapa da transação falhar.
        """
        with self.transaction() as database:
            session = self.get_session(session_id)
            if session is None or session.status == SessionStatus.FINISHED:
                raise RuntimeError("A sessão não está pendente.")
            if session.status == SessionStatus.RUNNING:
                if snapshot is None:
                    raise ValueError("Um intervalo running exige snapshot confirmado.")
                self._close_interval(session_id, snapshot)
            elif snapshot is not None:
                raise ValueError("Uma sessão paused não deve receber snapshot de intervalo aberto.")
            row = database.execute(
                "SELECT MAX(ended_at) AS latest_end, "
                "MAX(CASE WHEN ended_at > started_at THEN 1 ELSE 0 END) AS has_study "
                "FROM study_intervals WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            finished_at = (
                max(session.created_at, row["latest_end"])
                if row["has_study"]
                else session.created_at
            )
            database.execute(
                "UPDATE sessions SET status = ?, finished_at = ? WHERE id = ?",
                (SessionStatus.FINISHED.value, finished_at, session_id),
            )
            session = self._require_session(session_id, SessionStatus.FINISHED)
        return session

    def _open_interval(self, session_id: int, started_at: int) -> StudyInterval:
        """Insere o intervalo antes de alterar o status, dentro da transação do chamador."""
        self._connection.execute(
            "INSERT INTO study_intervals (session_id, started_at, last_seen_at) VALUES (?, ?, ?)",
            (session_id, started_at, started_at),
        )
        self._connection.execute(
            "UPDATE sessions SET status = ? WHERE id = ?",
            (SessionStatus.RUNNING.value, session_id),
        )
        interval = self.get_open_interval(session_id)
        assert interval is not None
        return interval

    def _close_interval(self, session_id: int, snapshot: ClockSnapshot) -> None:
        """Valida a identidade e os limites sintéticos antes de encerrar o intervalo."""
        interval = self.get_open_interval(session_id)
        if (
            interval is None
            or snapshot.interval_id != interval.id
            or snapshot.started_at != interval.started_at
            or snapshot.elapsed_s < 0
            or snapshot.valid_until_utc_s != snapshot.started_at + snapshot.elapsed_s
            or snapshot.valid_until_utc_s < interval.last_seen_at
        ):
            raise ValueError("Snapshot incompatível com o intervalo aberto ou seu checkpoint.")
        self._connection.execute(
            "UPDATE study_intervals SET last_seen_at = ?, ended_at = ? WHERE id = ?",
            (snapshot.valid_until_utc_s, snapshot.valid_until_utc_s, interval.id),
        )

    def _require_session(self, session_id: int, status: SessionStatus) -> Session:
        """Exige o estado esperado sem aceitar transições implícitas ou sessões ausentes."""
        session = self.get_session(session_id)
        if session is None or session.status != status:
            raise RuntimeError("Estado da sessão incompatível com a operação.")
        return session

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> Session:
        """Converte uma linha SQLite no modelo imutável de sessão."""
        return Session(
            id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            status=SessionStatus(row["status"]),
        )

    @staticmethod
    def _interval_from_row(row: sqlite3.Row) -> StudyInterval:
        """Converte uma linha SQLite no modelo imutável de intervalo."""
        return StudyInterval(
            id=row["id"],
            session_id=row["session_id"],
            started_at=row["started_at"],
            last_seen_at=row["last_seen_at"],
            ended_at=row["ended_at"],
        )
