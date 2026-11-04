"""Validação de entrada antes de qualquer persistência de dados de estudo."""

import unicodedata

from app.config import (
    DEFAULT_SESSION_NAME,
    MAX_SESSION_NAME_LENGTH,
    MAX_STUDY_TYPE_NAME_LENGTH,
)


def normalize_session_name(name: str) -> str:
    """Normaliza o nome e rejeita entradas que ultrapassem o limite do MVP.

    Args:
        name: Entrada original, inclusive vazia ou com caracteres de controle.

    Returns:
        Nome sem controles e espaços nas pontas, ou o nome padrão.

    Raises:
        ValueError: Se o nome normalizado exceder 120 caracteres.
    """
    normalized = "".join(char for char in name if not unicodedata.category(char).startswith("C"))
    normalized = normalized.strip() or DEFAULT_SESSION_NAME
    if len(normalized) > MAX_SESSION_NAME_LENGTH:
        raise ValueError("O nome da sessão deve ter até 120 caracteres.")
    return normalized


def normalize_study_type_name(name: str) -> str:
    """Normaliza Unicode e espaços; recusa vazio, excesso e nome reservado."""
    compatible = unicodedata.normalize("NFKC", name)
    cleaned = "".join(
        " " if char.isspace() else char
        for char in compatible
        if char.isspace() or not unicodedata.category(char).startswith("C")
    )
    normalized = " ".join(cleaned.split())
    if not normalized:
        raise ValueError("Informe um nome para o tipo de estudo.")
    if len(normalized) > MAX_STUDY_TYPE_NAME_LENGTH:
        raise ValueError("O nome do tipo deve ter até 60 caracteres.")
    if normalized.casefold() == "sem tipo":
        raise ValueError("O nome Sem tipo é reservado.")
    return normalized
