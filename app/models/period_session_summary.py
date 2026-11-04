"""Contribuição de uma sessão no período filtrado."""

from dataclasses import dataclass
from datetime import date

from app.models.study_color import StudyColor


@dataclass(frozen=True, slots=True)
class PeriodSessionSummary:
    session_id: int
    name: str
    study_type_id: int | None
    type_name: str
    color_key: StudyColor | None
    day: date
    duration_s: int
