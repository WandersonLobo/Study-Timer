"""Contratos normativos do cronômetro; regras serão implementadas na próxima etapa."""

from app.database.repository import StudyRepository
from app.models import PauseReason, Session
from app.services.clock_service import ClockService
from app.validation import normalize_session_name


class TimerService:
    """Coordena sessão única, transações, checkpoints e recuperação.

    Os comandos ainda levantam NotImplementedError e não são ligados à interface.
    """

    def __init__(self, repository: StudyRepository, clock: ClockService) -> None:
        self._repository = repository
        self._clock = clock

    def start_session(self, name: str) -> Session:
        """Criará sessão paused e intervalo, mudando para running atomicamente."""
        name = normalize_session_name(name)
        raise NotImplementedError("Implementar início transacional da sessão.")

    def pause_session(self, reason: PauseReason) -> Session:
        """Encerrará o intervalo no último tick válido e manterá sessão pendente."""
        raise NotImplementedError("Implementar pausa transacional e diagnóstico.")

    def resume_session(self) -> Session:
        """Abrirá um novo intervalo sem contabilizar o tempo pausado."""
        raise NotImplementedError("Implementar retomada da sessão pendente.")

    def finish_session(self) -> Session:
        """Concluirá a sessão usando o maior término confirmado dos intervalos."""
        raise NotImplementedError("Implementar finalização com finished_at sintético.")

    def recover_pending(self) -> Session | None:
        """Fechará o intervalo interrompido em last_seen_at e retornará paused."""
        raise NotImplementedError("Implementar recuperação conservadora após reinício.")

    def heartbeat(self) -> None:
        """Persistirá o checkpoint confirmado sem alterar a duração de referência."""
        raise NotImplementedError("Implementar checkpoint de aproximadamente cinco segundos.")

    def get_active_session(self) -> Session | None:
        """Consulta a sessão running/paused sem tocar na interface."""
        return self._repository.get_pending_session()
