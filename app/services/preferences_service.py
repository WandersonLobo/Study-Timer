"""Preferência local de aparência, pronta para integração posterior com a UI."""

from app.database.repository import StudyRepository
from app.models import AppearanceMode


class PreferencesService:
    """Consulta e confirma a aparência sem importar CustomTkinter."""

    def __init__(self, repository: StudyRepository) -> None:
        self._repository = repository

    def get_appearance_mode(self) -> AppearanceMode:
        """Obtém a escolha persistida, inicialmente escura."""
        return self._repository.get_appearance_mode()

    def set_appearance_mode(self, mode: AppearanceMode) -> None:
        """Só confirma a escolha após COMMIT; valor inválido é recusado."""
        self._repository.set_appearance_mode(AppearanceMode(mode))
