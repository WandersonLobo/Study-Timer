"""Centraliza SQL e valida invariantes cruzadas antes do COMMIT."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.models import (
    AppearanceMode,
    ClockSnapshot,
    Session,
    SessionStatus,
    StudyColor,
    StudyInterval,
    StudyType,
)
from app.validation import normalize_session_name, normalize_study_type_name


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
            "SELECT id, name, created_at, finished_at, status, study_type_id "
            "FROM sessions WHERE status IN (?, ?)",
            (SessionStatus.RUNNING.value, SessionStatus.PAUSED.value),
        ).fetchone()
        if row is None:
            return None
        return self._session_from_row(row)

    def get_session(self, session_id: int) -> Session | None:
        """Consulta uma sessão pelo identificador, inclusive após sua finalização."""
        row = self._connection.execute(
            "SELECT id, name, created_at, finished_at, status, study_type_id "
            "FROM sessions WHERE id = ?",
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

    def start_session(
        self, name: str, started_at: int, study_type_id: int | None = None
    ) -> tuple[Session, StudyInterval]:
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
            if study_type_id is not None:
                study_type = self._require_study_type(study_type_id)
                if study_type.is_archived:
                    raise ValueError("O tipo de estudo está arquivado.")
            cursor = database.execute(
                "INSERT INTO sessions (name, created_at, status, study_type_id) "
                "VALUES (?, ?, ?, ?)",
                (name, started_at, SessionStatus.PAUSED.value, study_type_id),
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

    def save_checkpoint(self, session_id: int, snapshot: ClockSnapshot) -> None:
        """Confirma somente o último tick aceito, sem fechar o intervalo.

        Não consulta a hora civil e rejeita snapshots inconsistentes ou anteriores
        ao checkpoint já persistido. Uma exceção significa que não houve COMMIT.
        """
        with self.transaction() as database:
            self._require_session(session_id, SessionStatus.RUNNING)
            interval = self._validate_snapshot(session_id, snapshot)
            database.execute(
                "UPDATE study_intervals SET last_seen_at = ? WHERE id = ?",
                (snapshot.valid_until_utc_s, interval.id),
            )

    def recover_pending(self) -> Session | None:
        """Recupera running como paused exatamente no checkpoint persistido.

        É idempotente: sessões paused e ausência de pendência não mudam. Todo o
        fechamento ocorre em uma transação, sem usar a hora de abertura do app.
        """
        with self.transaction() as database:
            session = self.get_pending_session()
            if session is not None and session.status == SessionStatus.RUNNING:
                interval = self.get_open_interval(session.id)
                if interval is None:
                    raise sqlite3.IntegrityError("Sessão running sem intervalo aberto.")
                database.execute(
                    "UPDATE study_intervals SET ended_at = last_seen_at WHERE id = ?",
                    (interval.id,),
                )
                database.execute(
                    "UPDATE sessions SET status = ? WHERE id = ?",
                    (SessionStatus.PAUSED.value, session.id),
                )
                session = self._require_session(session.id, SessionStatus.PAUSED)
        return session

    def get_report_intervals(
        self, start: int, end: int, active_interval_id: int | None = None
    ) -> list[tuple[Session, StudyInterval]]:
        """Lê intervalos candidatos e o intervalo ativo para validar o snapshot.

        As fronteiras são UTC meio abertas. O serviço calcula a interseção e
        substitui o checkpoint; SQL não soma o snapshot ao tempo persistido.
        """
        rows = self._connection.execute(
            "SELECT s.id AS session_id, s.name, s.created_at, s.finished_at, s.status, "
            "s.study_type_id, "
            "i.id, i.started_at, i.last_seen_at, i.ended_at FROM study_intervals i "
            "JOIN sessions s ON s.id = i.session_id "
            "WHERE (i.started_at < ? AND COALESCE(i.ended_at, i.last_seen_at) > ?) "
            "OR (i.id = ? AND i.ended_at IS NULL) ORDER BY i.id",
            (end, start, active_interval_id),
        ).fetchall()
        return [
            (
                Session(
                    row["session_id"],
                    row["name"],
                    row["created_at"],
                    row["finished_at"],
                    SessionStatus(row["status"]),
                    row["study_type_id"],
                ),
                self._interval_from_row(row),
            )
            for row in rows
        ]

    def get_zero_duration_sessions(self, start: int, end: int) -> list[Session]:
        """Lista sessões sem segundos persistidos no dia de criação, uma vez só."""
        rows = self._connection.execute(
            "SELECT id, name, created_at, finished_at, status, study_type_id FROM sessions s "
            "WHERE created_at >= ? AND created_at < ? AND NOT EXISTS "
            "(SELECT 1 FROM study_intervals i WHERE i.session_id = s.id "
            "AND COALESCE(i.ended_at, i.last_seen_at) > i.started_at) ORDER BY id",
            (start, end),
        ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def get_period_intervals(
        self, start: int, end: int, active_interval_id: int | None = None
    ) -> list[tuple[Session, StudyInterval, StudyType | None]]:
        """Busca intervalos e a apresentação histórica de tipos em um LEFT JOIN."""
        rows = self._connection.execute(
            "SELECT s.id AS session_id, s.name, s.created_at, s.finished_at, s.status, "
            "s.study_type_id, i.id, i.started_at, i.last_seen_at, i.ended_at, "
            "t.id AS type_id, t.name AS type_name, t.color_key, t.is_archived "
            "FROM study_intervals i JOIN sessions s ON s.id = i.session_id "
            "LEFT JOIN study_types t ON t.id = s.study_type_id "
            "WHERE (i.started_at < ? AND COALESCE(i.ended_at, i.last_seen_at) > ?) "
            "OR (i.id = ? AND i.ended_at IS NULL) ORDER BY i.id",
            (end, start, active_interval_id),
        ).fetchall()
        return [
            (
                Session(
                    row["session_id"],
                    row["name"],
                    row["created_at"],
                    row["finished_at"],
                    SessionStatus(row["status"]),
                    row["study_type_id"],
                ),
                self._interval_from_row(row),
                self._report_type_from_row(row),
            )
            for row in rows
        ]

    def get_zero_duration_report_sessions(
        self, start: int, end: int
    ) -> list[tuple[Session, StudyType | None]]:
        """Inclui metadados de sessões zeradas, sem uma consulta por sessão."""
        rows = self._connection.execute(
            "SELECT s.id, s.name, s.created_at, s.finished_at, s.status, s.study_type_id, "
            "t.id AS type_id, t.name AS type_name, t.color_key, t.is_archived "
            "FROM sessions s LEFT JOIN study_types t ON t.id = s.study_type_id "
            "WHERE s.created_at >= ? AND s.created_at < ? AND NOT EXISTS "
            "(SELECT 1 FROM study_intervals i WHERE i.session_id = s.id "
            "AND COALESCE(i.ended_at, i.last_seen_at) > i.started_at) ORDER BY s.id",
            (start, end),
        ).fetchall()
        return [(self._session_from_row(row), self._report_type_from_row(row)) for row in rows]

    @staticmethod
    def _report_type_from_row(row: sqlite3.Row) -> StudyType | None:
        if row["type_id"] is None:
            return None
        return StudyType(
            row["type_id"], row["type_name"], StudyColor(row["color_key"]), bool(row["is_archived"])
        )

    def get_study_type(self, type_id: int) -> StudyType | None:
        """Consulta um tipo, inclusive arquivado, pelo identificador estável."""
        row = self._connection.execute(
            "SELECT id, name, color_key, is_archived FROM study_types WHERE id = ?",
            (type_id,),
        ).fetchone()
        return None if row is None else self._study_type_from_row(row)

    def list_study_types(self, *, include_archived: bool = False) -> list[StudyType]:
        """Ordena pela chave Unicode sem ocultar arquivados quando solicitados."""
        rows = self._connection.execute(
            "SELECT id, name, color_key, is_archived FROM study_types "
            "WHERE is_archived = 0 OR ? ORDER BY name_key, id",
            (include_archived,),
        ).fetchall()
        return [self._study_type_from_row(row) for row in rows]

    def create_study_type(self, name: str, color_key: StudyColor) -> StudyType:
        """Cria um tipo com nome único em todo o catálogo, inclusive arquivados."""
        name = normalize_study_type_name(name)
        color_key = StudyColor(color_key)
        with self.transaction() as database:
            self._require_unique_study_type_name(name)
            cursor = database.execute(
                "INSERT INTO study_types (name, name_key, color_key, is_archived) "
                "VALUES (?, ?, ?, 0)",
                (name, name.casefold(), color_key.value),
            )
            assert cursor.lastrowid is not None
            study_type = self._require_study_type(cursor.lastrowid)
        return study_type

    def update_study_type(self, type_id: int, name: str, color_key: StudyColor) -> StudyType:
        """Altera somente a apresentação, preservando vínculos e durações."""
        name = normalize_study_type_name(name)
        color_key = StudyColor(color_key)
        with self.transaction() as database:
            self._require_study_type(type_id)
            self._require_unique_study_type_name(name, type_id)
            database.execute(
                "UPDATE study_types SET name = ?, name_key = ?, color_key = ? WHERE id = ?",
                (name, name.casefold(), color_key.value, type_id),
            )
            study_type = self._require_study_type(type_id)
        return study_type

    def set_study_type_archived(self, type_id: int, archived: bool) -> StudyType:
        """Oculta/reativa sem apagar; uma pendência impede seu arquivamento."""
        with self.transaction() as database:
            self._require_study_type(type_id)
            pending = self.get_pending_session()
            if archived and pending is not None and pending.study_type_id == type_id:
                raise ValueError("O tipo de uma sessão pendente não pode ser arquivado.")
            database.execute(
                "UPDATE study_types SET is_archived = ? WHERE id = ?", (archived, type_id)
            )
            study_type = self._require_study_type(type_id)
        return study_type

    def get_appearance_mode(self) -> AppearanceMode:
        """Obtém o registro único; ausência não é tratada como escolha padrão."""
        row = self._connection.execute(
            "SELECT appearance_mode FROM app_preferences WHERE id = 1"
        ).fetchone()
        if row is None:
            raise sqlite3.IntegrityError("Preferência de aparência ausente.")
        return AppearanceMode(row[0])

    def set_appearance_mode(self, mode: AppearanceMode) -> None:
        """Confirma uma preferência reconhecida em escrita atômica."""
        mode = AppearanceMode(mode)
        with self.transaction() as database:
            cursor = database.execute(
                "UPDATE app_preferences SET appearance_mode = ? WHERE id = 1", (mode.value,)
            )
            if cursor.rowcount != 1:
                raise sqlite3.IntegrityError("Preferência de aparência ausente.")

    def _require_study_type(self, type_id: int) -> StudyType:
        study_type = self.get_study_type(type_id)
        if study_type is None:
            raise ValueError("O tipo de estudo não existe.")
        return study_type

    def _require_unique_study_type_name(self, name: str, type_id: int | None = None) -> None:
        duplicate = self._connection.execute(
            "SELECT id FROM study_types WHERE name_key = ? AND (? IS NULL OR id != ?)",
            (name.casefold(), type_id, type_id),
        ).fetchone()
        if duplicate is not None:
            raise ValueError("Já existe um tipo com esse nome, ativo ou arquivado.")

    @staticmethod
    def _study_type_from_row(row: sqlite3.Row) -> StudyType:
        return StudyType(
            row["id"], row["name"], StudyColor(row["color_key"]), bool(row["is_archived"])
        )

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
        interval = self._validate_snapshot(session_id, snapshot)
        self._connection.execute(
            "UPDATE study_intervals SET last_seen_at = ?, ended_at = ? WHERE id = ?",
            (snapshot.valid_until_utc_s, snapshot.valid_until_utc_s, interval.id),
        )

    def _validate_snapshot(self, session_id: int, snapshot: ClockSnapshot) -> StudyInterval:
        """Compartilha a mesma validação entre checkpoints e fechamento."""
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
        return interval

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
            study_type_id=row["study_type_id"],
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
