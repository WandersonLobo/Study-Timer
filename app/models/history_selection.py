"""Seleção imutável; Todos e Sem tipo são filtros distintos."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.models.report_period import ReportPeriod


@dataclass(frozen=True, slots=True)
class HistorySelection:
    period: ReportPeriod
    reference: date
    type_filter: Literal["all", "untyped", "type"] = "all"
    study_type_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "period", ReportPeriod(self.period))
        if not 1 <= self.reference.year <= 9998:
            raise ValueError("Data fora do intervalo suportado.")
        if self.type_filter not in ("all", "untyped", "type"):
            raise ValueError("Filtro de tipo inválido.")
        if (self.type_filter == "type") != (self.study_type_id is not None):
            raise ValueError("Identificador incompatível com o filtro.")
        if self.study_type_id is not None and self.study_type_id <= 0:
            raise ValueError("Identificador de tipo inválido.")
