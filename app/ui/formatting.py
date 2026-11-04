"""Formatação de totais já agregados pelo serviço."""


def format_minutes(seconds: int) -> str:
    """Trunca minutos uma vez, depois da agregação de segundos."""
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def format_clock(seconds: int) -> str:
    """Apresenta detalhes com precisão de segundos, inclusive sessões zeradas."""
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
