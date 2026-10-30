"""Ciclo básico de sessões com relógio confiável e persistência transacional."""

from app.database.repository import StudyRepository
from app.models import ClockSnapshot, PauseReason, Session, SessionStatus
from app.services.clock_service import ClockService
from app.validation import normalize_session_name


class TimerService:
    """Coordena sessão única, transações, checkpoints e recuperação.

    Início, pausa, retomada e finalização funcionam sem interface. Heartbeat e
    recuperação de processo permanecem reservados ao próximo incremento.
    """

    def __init__(self, repository: StudyRepository, clock: ClockService) -> None:
        self._repository = repository
        self._clock = clock

    def start_session(self, name: str) -> Session:
        """Cria sessão e primeiro intervalo antes de iniciar o relógio.

        Raises:
            RuntimeError: Se já houver sessão pendente ou relógio em execução.
            ValueError: Se o nome não atender ao limite de 120 caracteres.
        """
        name = normalize_session_name(name)
        if self.get_active_session() is not None:
            raise RuntimeError("Finalize a sessão pendente antes de iniciar outra.")
        self._require_stopped_clock()
        anchor = self._clock.capture_anchor()
        session, interval = self._repository.start_session(name, int(anchor.wall_time_s))
        self._clock.start_interval(interval.id, anchor)
        return session

    def pause_session(self, reason: PauseReason) -> Session:
        """Congela a contagem e persiste intervalo encerrado e sessão paused.

        Uma pausa USER valida um último tick. Os demais motivos usam somente o
        snapshot já aceito. Falhas de escrita deixam o relógio congelado e o
        snapshot disponível para repetir a operação, sem acumular tempo adicional.
        """
        session = self._require_active_session(SessionStatus.RUNNING)
        snapshot = self._freeze_interval(session.id, reason)
        return self._repository.pause_session(session.id, snapshot)

    def resume_session(self) -> Session:
        """Abre outro intervalo na sessão paused, sem incluir o tempo da pausa."""
        session = self._require_active_session(SessionStatus.PAUSED)
        self._require_stopped_clock()
        anchor = self._clock.capture_anchor()
        resumed, interval = self._repository.resume_session(session.id, int(anchor.wall_time_s))
        self._clock.start_interval(interval.id, anchor)
        return resumed

    def finish_session(self) -> Session:
        """Finaliza uma sessão running ou paused e limpa o relógio após COMMIT.

        Sessões paused não leem a fonte de tempo. Se a gravação falhar, conserva
        o snapshot congelado para uma tentativa posterior, sem concluir em memória.
        """
        session = self.get_active_session()
        if session is None:
            raise RuntimeError("Não existe sessão pendente para finalizar.")
        snapshot = None
        if session.status == SessionStatus.RUNNING:
            snapshot = self._freeze_interval(session.id, PauseReason.USER)
        else:
            self._require_stopped_clock()
        finished = self._repository.finish_session(session.id, snapshot)
        self._clock.reset()
        return finished

    def recover_pending(self) -> Session | None:
        """Fechará o intervalo interrompido em last_seen_at e retornará paused."""
        raise NotImplementedError("Implementar recuperação conservadora após reinício.")

    def heartbeat(self) -> None:
        """Persistirá o checkpoint confirmado sem alterar a duração de referência."""
        raise NotImplementedError("Implementar checkpoint de aproximadamente cinco segundos.")

    def get_active_session(self) -> Session | None:
        """Consulta a sessão running/paused sem tocar na interface."""
        return self._repository.get_pending_session()

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
        interval = self._repository.get_open_interval(session_id)
        snapshot = self._clock.get_snapshot()
        if (
            interval is None
            or snapshot is None
            or snapshot.interval_id != interval.id
            or snapshot.started_at != interval.started_at
        ):
            raise RuntimeError("Intervalo sem relógio correspondente; recuperação necessária.")
        if reason == PauseReason.USER:
            self._clock.tick()
        frozen = self._clock.pause(reason)
        assert frozen is not None
        return frozen
