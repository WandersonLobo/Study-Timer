"""Contratos de relatórios por fronteiras locais e snapshot imutável."""

from datetime import date

from app.database.repository import StudyRepository
from app.models import ClockSnapshot, PeriodTotals, SessionSummary


class ReportService:
    """Reserva consultas agregadas em segundos, sem formatação ou widgets.

    now=None representará ausência de relógio ativo, usando last_seen_at.
    O fuso Windows será resolvido em cada consulta; nenhum offset fixo é assumido.
    """

    def __init__(self, repository: StudyRepository) -> None:
        self._repository = repository

    def get_totals(self, reference: date, now: ClockSnapshot | None) -> PeriodTotals:
        """Calculará os cartões fixos de hoje, semana e mês atual."""
        raise NotImplementedError("Implementar agregação local e snapshot sem dupla soma.")

    def get_month_days(self, year: int, month: int, now: ClockSnapshot | None) -> dict[date, int]:
        """Retornará os segundos de cada dia do mês exibido no calendário."""
        raise NotImplementedError("Implementar distribuição de intervalos por dia local.")

    def get_day_sessions(self, day: date, now: ClockSnapshot | None) -> list[SessionSummary]:
        """Retornará a parcela de cada sessão atribuída ao dia selecionado."""
        raise NotImplementedError("Implementar detalhes diários e sessões de zero segundos.")
