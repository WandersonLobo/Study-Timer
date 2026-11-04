"""Faixa temporal do gráfico, sem dependência de pixels."""

from dataclasses import dataclass
from datetime import date

from app.models.study_type_total import StudyTypeTotal


@dataclass(frozen=True, slots=True)
class ReportBucket:
    start_utc: int
    end_utc: int
    label: str
    day: date
    totals: tuple[StudyTypeTotal, ...]

    @property
    def duration_s(self) -> int:
        return sum(item.duration_s for item in self.totals)
