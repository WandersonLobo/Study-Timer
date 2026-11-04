"""Relatórios em segundos, por fronteiras locais e snapshot sem dupla soma."""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo

from tzlocal import reload_localzone

from app.database.repository import StudyRepository
from app.models import ClockSnapshot, PeriodTotals, Session, SessionSummary


class ReportService:
    """Agrega em UTC usando fronteiras locais históricas, inclusive DST.

    A fonte de fuso é injetável. Por padrão relê o fuso Windows a cada consulta;
    não armazena o offset atual como se fosse válido para outras datas.
    """

    def __init__(
        self, repository: StudyRepository, timezone_source: Callable[[], tzinfo] = reload_localzone
    ) -> None:
        self._repository = repository
        self._timezone_source = timezone_source

    def get_today(self) -> date:
        """Obtém a data civil atual no fuso selecionado pelo sistema."""
        return datetime.now(self._timezone_source()).date()

    def get_totals(self, reference: date, now: ClockSnapshot | None) -> PeriodTotals:
        """Calcula hoje, segunda a domingo e mês da referência, em segundos."""
        zone = self._timezone_source()
        week = reference - timedelta(days=reference.weekday())
        month = reference.replace(day=1)
        periods = [
            self._bounds(reference, reference + timedelta(days=1), zone),
            self._bounds(week, week + timedelta(days=7), zone),
            self._bounds(month, self._next_month(month), zone),
        ]
        rows = self._segments(min(p[0] for p in periods), max(p[1] for p in periods), now)
        totals = [
            sum(self._overlap(start, end, a, b) for _, start, end in rows) for a, b in periods
        ]
        return PeriodTotals(*totals)

    def get_month_days(self, year: int, month: int, now: ClockSnapshot | None) -> dict[date, int]:
        """Retorna todos os dias, incluindo os de zero segundos, do mês exibido."""
        zone = self._timezone_source()
        first = date(year, month, 1)
        following = self._next_month(first)
        start, end = self._bounds(first, following, zone)
        rows = self._segments(start, end, now)
        totals: dict[date, int] = {}
        day = first
        while day < following:
            a, b = self._bounds(day, day + timedelta(days=1), zone)
            totals[day] = sum(self._overlap(start, end, a, b) for _, start, end in rows)
            day += timedelta(days=1)
        return totals

    def get_day_sessions(self, day: date, now: ClockSnapshot | None) -> list[SessionSummary]:
        """Lista a parcela diária, incluindo sessões zeradas no dia de criação."""
        zone = self._timezone_source()
        start, end = self._bounds(day, day + timedelta(days=1), zone)
        rows = self._segments(start, end, now)
        summaries: dict[int, SessionSummary] = {}
        positive: set[int] = set()
        for session, a, b in rows:
            if b > a:
                positive.add(session.id)
            seconds = self._overlap(a, b, start, end)
            if seconds:
                previous = summaries.get(session.id)
                summaries[session.id] = SessionSummary(
                    session.id, session.name, seconds + (previous.duration_s if previous else 0)
                )
        for session in self._repository.get_zero_duration_sessions(start, end):
            if session.id not in positive:
                summaries.setdefault(session.id, SessionSummary(session.id, session.name, 0))
        return sorted(
            summaries.values(), key=lambda s: (-s.duration_s, s.name.casefold(), s.session_id)
        )

    def _segments(
        self, start: int, end: int, now: ClockSnapshot | None
    ) -> list[tuple[Session, int, int]]:
        if now is not None and (
            now.elapsed_s < 0 or now.valid_until_utc_s != now.started_at + now.elapsed_s
        ):
            raise ValueError("Snapshot temporal inconsistente.")
        rows = self._repository.get_report_intervals(start, end, now.interval_id if now else None)
        segments = []
        for session, interval in rows:
            until = interval.ended_at if interval.ended_at is not None else interval.last_seen_at
            if now is not None and interval.ended_at is None and interval.id == now.interval_id:
                if now.started_at != interval.started_at or now.valid_until_utc_s < until:
                    raise ValueError("Snapshot incompatível com o checkpoint.")
                until = now.valid_until_utc_s
            segments.append((session, interval.started_at, until))
        return segments

    @staticmethod
    def _bounds(first: date, following: date, zone: tzinfo) -> tuple[int, int]:
        # timestamp converte cada fronteira independentemente; um dia não é sempre 24 h.
        return (
            int(datetime.combine(first, time.min, zone).timestamp()),
            int(datetime.combine(following, time.min, zone).timestamp()),
        )

    @staticmethod
    def _next_month(first: date) -> date:
        return (
            date(first.year + 1, 1, 1)
            if first.month == 12
            else first.replace(month=first.month + 1)
        )

    @staticmethod
    def _overlap(start: int, end: int, a: int, b: int) -> int:
        return max(0, min(end, b) - max(start, a))
