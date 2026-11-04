"""Totais imutáveis dos períodos exibidos no histórico."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PeriodTotals:
    """Totais dos cartões fixos, expressos em segundos antes da formatação."""

    today_s: int
    week_s: int
    month_s: int
