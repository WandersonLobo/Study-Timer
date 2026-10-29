"""Fonte de tempo injetável e fronteira da validação de ticks."""

import time
from typing import Protocol

from app.models import ClockReading, ClockSnapshot


class ClockSource(Protocol):
    """Permite substituir os relógios reais por amostras controladas nos testes."""

    def read(self) -> ClockReading:
        """Captura os relógios civil e monotônico em sequência próxima."""
        ...


class SystemClock:
    """Captura amostras reais sem decidir se o tick deve ser contabilizado."""

    def read(self) -> ClockReading:
        """Retorna a âncora civil e os nanossegundos monotônicos atuais."""
        return ClockReading(wall_time_s=time.time(), monotonic_ns=time.monotonic_ns())


class ClockService:
    """Reserva o estado do relógio validado; detector de lacunas ainda pendente."""

    def __init__(self, source: ClockSource) -> None:
        self._source = source

    def get_snapshot(self) -> ClockSnapshot | None:
        """Retornará o intervalo ativo até o último tick confiável.

        Raises:
            NotImplementedError: Até implementar âncora, lacunas e divergência civil.
        """
        raise NotImplementedError("Implementar validação de ticks conforme seção 4 do PDF.")
