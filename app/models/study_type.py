"""Modelo imutável de uma classificação de estudo."""

from dataclasses import dataclass

from app.models.study_color import StudyColor


@dataclass(frozen=True, slots=True)
class StudyType:
    """Conserva identidade e cor sem armazenar a lista de sessões."""

    id: int
    name: str
    color_key: StudyColor
    is_archived: bool = False

    def __post_init__(self) -> None:
        """Recusa uma chave fora da paleta também na construção direta."""
        object.__setattr__(self, "color_key", StudyColor(self.color_key))
