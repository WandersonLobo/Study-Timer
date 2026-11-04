"""Resultado único e coerente para métricas, gráfico e detalhes."""

from dataclasses import dataclass
from datetime import date

from app.models.history_selection import HistorySelection
from app.models.period_session_summary import PeriodSessionSummary
from app.models.report_bucket import ReportBucket
from app.models.study_type_total import StudyTypeTotal


@dataclass(frozen=True, slots=True)
class PeriodReport:
    selection: HistorySelection
    start_day: date
    end_day: date
    start_utc: int
    end_utc: int
    total_s: int
    average_s: float
    average_days: int
    buckets: tuple[ReportBucket, ...]
    ranking: tuple[StudyTypeTotal, ...]
    sessions: tuple[PeriodSessionSummary, ...]
    filter_name: str | None = None
