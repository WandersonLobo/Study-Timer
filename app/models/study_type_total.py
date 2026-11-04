"""Contribuição de um tipo no resultado selecionado."""

from dataclasses import dataclass

from app.models.study_color import StudyColor


@dataclass(frozen=True, slots=True)
class StudyTypeTotal:
    type_id: int | None
    name: str
    color_key: StudyColor | None
    duration_s: int
    percentage: float
