"""Ciclo de sessões, checkpoints e recuperação com persistência transacional."""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.database.repository import StudyRepository
from app.models import ClockSnapshot, PauseReason, Session, SessionStatus
from app.services.clock_service import ClockService
from app.validation import normalize_session_name

logger = logging.getLogger("studytimer.timer")


class TimerService:
    """Coordena sessão única, transações, checkpoints e recuperação.

    Os comandos funcionam sem interface. O chamador agenda ticks e heartbeats,
    trata exceções e só informa sucesso quando a operação retorna após COMMIT.
    """

    def __init__(self, repository: StudyRepository, clock: ClockService) -> None:
        self._repository = repository
        self._clock = clock
        self._persistence_failed = False

    @property
    def persistence_failed(self) -> bool:
        """Indica falha de persistência ainda não resolvida por um comando confirmado.

        A sessão pode continuar running no banco enquanto o relógio está parado.
        Uma consulta ou heartbeat sem trabalho não confirma dados nem limpa a falha.
        """
        return self._persistence_failed

    def start_session(self, name: str) -> Session:
        """Cria sessão e primeiro intervalo antes de iniciar o relógio.

        Raises:
            RuntimeError: Se já houver sessão pendente ou relógio em execução.
            ValueError: Se o nome não atender ao limite de 120 caracteres.
        """
        name = normalize_session_name(name)
        with self._persistence_operation():
            if self.get_active_session() is not None:
                raise RuntimeError("Finalize a sessão pendente antes de iniciar outra.")
            self._require_stopped_clock()
            anchor = self._clock.capture_anchor()
            session, interval = self._repository.start_session(name, int(anchor.wall_time_s))
        self._persistence_failed = False
        self._clock.start_interval(interval.id, anchor)
        return session

    def pause_session(self, reason: PauseReason) -> Session:
        """Congela a contagem e persiste intervalo encerrado e sessão paused.

        Uma pausa USER valida um último tick. Os demais motivos usam somente o
        snapshot já aceito. Falhas de escrita deixam o relógio congelado e o
        snapshot disponível para repetir a operação, sem acumular tempo adicional.
        """
        with self._persistence_operation():
            session = self._require_active_session(SessionStatus.RUNNING)
            snapshot = self._freeze_interval(session.id, reason)
            paused = self._repository.pause_session(session.id, snapshot)
        self._persistence_failed = False
        return paused

    def resume_session(self) -> Session:
        """Abre outro intervalo na sessão paused, sem incluir o tempo da pausa."""
        with self._persistence_operation():
            session = self._require_active_session(SessionStatus.PAUSED)
            self._require_stopped_clock()
            anchor = self._clock.capture_anchor()
            resumed, interval = self._repository.resume_session(session.id, int(anchor.wall_time_s))
        self._persistence_failed = False
        self._clock.start_interval(interval.id, anchor)
        return resumed

    def finish_session(self) -> Session:
        """Finaliza uma sessão running ou paused e limpa o relógio após COMMIT.

        Sessões paused não leem a fonte de tempo. Se a gravação falhar, conserva
        o snapshot congelado para uma tentativa posterior, sem concluir em memória.
        """
        with self._persistence_operation():
            session = self.get_active_session()
            if session is None:
                raise RuntimeError("Não existe sessão pendente para finalizar.")
            snapshot = None
            if session.status == SessionStatus.RUNNING:
                snapshot = self._freeze_interval(session.id, PauseReason.USER)
            else:
                self._require_stopped_clock()
            finished = self._repository.finish_session(session.id, snapshot)
        self._persistence_failed = False
        self._clock.reset()
        return finished

    def recover_pending(self) -> Session | None:
        """Recupera ao abrir o processo, sem ler relógios nem retomar a contagem.

        Exige relógio sem snapshot para não descartar tempo congelado do processo
        atual. Falhas propagam e não anunciam recuperação; repetir é seguro.
        """
        self._require_stopped_clock()
        if self._clock.get_snapshot() is not None:
            raise RuntimeError("Persista o snapshot atual antes de recuperar uma sessão.")
        with self._persistence_operation():
            session = self._repository.recover_pending()
        self._persistence_failed = False
        return session

    def heartbeat(self) -> None:
        """Persiste o snapshot aceito, sem amostrar ou aceitar tempo novo.

        O chamador agenda esta operação aproximadamente a cada cinco segundos,
        além dos ticks de 250 ms. Se o relógio estiver congelado, fecha o intervalo
        e persiste paused. Falhas congelam a contagem e propagam; uma nova chamada
        tenta salvar o mesmo corte, sem retomar automaticamente.
        """
        with self._persistence_operation():
            session = self.get_active_session()
            if session is None or session.status != SessionStatus.RUNNING:
                return
            snapshot = self._require_snapshot(session.id)
            if self._clock.is_running:
                self._repository.save_checkpoint(session.id, snapshot)
            else:
                self._repository.pause_session(session.id, snapshot)
        self._persistence_failed = False

    def get_active_session(self) -> Session | None:
        """Consulta a sessão running/paused sem tocar na interface."""
        return self._repository.get_pending_session()

    @contextmanager
    def _persistence_operation(self) -> Iterator[None]:
        """Congela em falhas SQLite, sem ocultar exceções nem registrar dados privados."""
        try:
            yield
        except sqlite3.Error as error:
            self._clock.pause(PauseReason.WRITE_FAILURE)
            self._persistence_failed = True
            logger.error("PERSISTENCE_FAILED type=%s", type(error).__name__)
            raise

    def _require_active_session(self, status: SessionStatus) -> Session:
        """Consulta o estado persistido, sem manter uma cópia mutável da sessão."""
        session = self.get_active_session()
        if session is None or session.status != status:
            raise RuntimeError("Estado da sessão incompatível com a operação.")
        return session

    def _require_stopped_clock(self) -> None:
        """Impede iniciar ou finalizar uma sessão paused com relógio ainda ativo."""
        if self._clock.is_running:
            raise RuntimeError("O relógio ainda possui um intervalo em execução.")

    def _freeze_interval(self, session_id: int, reason: PauseReason) -> ClockSnapshot:
        """Exige relógio correspondente ao banco antes de aceitar ou congelar tempo."""
        self._require_snapshot(session_id)
        if reason == PauseReason.USER:
            self._clock.tick()
        frozen = self._clock.pause(reason)
        assert frozen is not None
        return frozen

    def _require_snapshot(self, session_id: int) -> ClockSnapshot:
        """Rejeita snapshots ausentes ou pertencentes a outro intervalo."""
        interval = self._repository.get_open_interval(session_id)
        snapshot = self._clock.get_snapshot()
        if (
            interval is None
            or snapshot is None
            or snapshot.interval_id != interval.id
            or snapshot.started_at != interval.started_at
        ):
            raise RuntimeError("Intervalo sem relógio correspondente; recuperação necessária.")
        return snapshot
