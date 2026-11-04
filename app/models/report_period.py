"""Granularidades disponíveis no Histórico."""

from enum import StrEnum


class ReportPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
