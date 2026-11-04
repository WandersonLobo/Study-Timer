"""Operações do catálogo de tipos, sem widgets nem acesso direto a SQL."""

from app.database.repository import StudyRepository
from app.models import StudyColor, StudyType
from app.validation import normalize_study_type_name


class StudyTypeService:
    """Expõe o catálogo; comandos só retornam após confirmação do repositório."""

    def __init__(self, repository: StudyRepository) -> None:
        self._repository = repository

    def list_types(self, *, include_archived: bool = False) -> list[StudyType]:
        """Lista ativos, ou todo o catálogo para gerenciamento."""
        return self._repository.list_study_types(include_archived=include_archived)

    def create_type(self, name: str, color_key: StudyColor) -> StudyType:
        """Cria sem pré-cadastrar os exemplos dos mockups."""
        return self._repository.create_study_type(
            normalize_study_type_name(name), StudyColor(color_key)
        )

    def update_type(self, type_id: int, name: str, color_key: StudyColor) -> StudyType:
        """Renomeia/recolore mantendo a identidade e todas as sessões."""
        return self._repository.update_study_type(
            type_id, normalize_study_type_name(name), StudyColor(color_key)
        )

    def archive_type(self, type_id: int) -> StudyType:
        """Arquiva sem excluir; recusa o tipo de uma sessão pendente."""
        return self._repository.set_study_type_archived(type_id, True)

    def restore_type(self, type_id: int) -> StudyType:
        """Reativa o mesmo registro, sem duplicar sua identidade."""
        return self._repository.set_study_type_archived(type_id, False)
