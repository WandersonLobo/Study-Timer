"""Validação de entrada antes de qualquer persistência de dados de estudo."""

import unicodedata

from app.config import DEFAULT_SESSION_NAME, MAX_SESSION_NAME_LENGTH


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
