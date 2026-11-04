"""Relatórios em segundos, por fronteiras locais e snapshot sem dupla soma."""

import unicodedata
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from tzlocal import reload_localzone

from app.database.repository import StudyRepository
from app.models import (
    ClockSnapshot,
    HistorySelection,
    PeriodReport,
    PeriodSessionSummary,
    PeriodTotals,
    ReportBucket,
    ReportPeriod,
    Session,
    SessionSummary,
    StudyColor,
    StudyInterval,
    StudyType,
    StudyTypeTotal,
)


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

    def get_period_dates(self, selection: HistorySelection) -> tuple[date, date]:
        """Resolve fronteiras civis sem depender dos widgets ou do relógio ativo."""
        reference = selection.reference
        if selection.period == ReportPeriod.DAY:
            return reference, reference + timedelta(days=1)
        if selection.period == ReportPeriod.WEEK:
            first = date.fromordinal(max(1, reference.toordinal() - reference.weekday()))
            return first, first + timedelta(days=7)
        first = reference.replace(day=1)
        return first, self._next_month(first)

    def get_period_report(
        self, selection: HistorySelection, now: ClockSnapshot | None = None
    ) -> PeriodReport:
        """Entrega gráfico, ranking e sessões calculados sobre os mesmos segundos.

        Consultas usam metadados em lote, inclusive tipos arquivados. O snapshot
        substitui o checkpoint; nenhum relatório confirma escrita ou aceita ticks.
        """
        zone = self._timezone_source()
        first, following = self.get_period_dates(selection)
        start, end = self._bounds(first, following, zone)
        self._validate_report_snapshot(now)
        rows = self._repository.get_period_intervals(start, end, now.interval_id if now else None)
        limits = self._bucket_limits(selection.period, first, following, zone)
        per_bucket: list[dict[int | None, int]] = [{} for _ in limits]
        seconds_by_type: dict[int | None, int] = {}
        metadata: dict[int | None, tuple[str, StudyColor | None]] = {}
        summaries: dict[int, PeriodSessionSummary] = {}
        positive: set[int] = set()
        for session, interval, study_type in rows:
            until = self._report_interval_end(interval, now)
            if until > interval.started_at:
                positive.add(session.id)
            if not self._matches_type(selection, session.study_type_id):
                continue
            seconds = self._overlap(interval.started_at, until, start, end)
            if not seconds:
                continue
            type_id = session.study_type_id
            name, color = self._type_metadata(study_type)
            metadata[type_id] = name, color
            seconds_by_type[type_id] = seconds_by_type.get(type_id, 0) + seconds
            local_day = self._local_datetime(max(start, interval.started_at), zone).date()
            previous = summaries.get(session.id)
            summaries[session.id] = PeriodSessionSummary(
                session.id,
                session.name,
                type_id,
                name,
                color,
                min(local_day, previous.day) if previous else local_day,
                seconds + (previous.duration_s if previous else 0),
            )
            for values, (a, b, _, _) in zip(per_bucket, limits, strict=True):
                contribution = self._overlap(interval.started_at, until, a, b)
                if contribution:
                    values[type_id] = values.get(type_id, 0) + contribution
        for session, study_type in self._repository.get_zero_duration_report_sessions(start, end):
            if session.id in positive or not self._matches_type(selection, session.study_type_id):
                continue
            name, color = self._type_metadata(study_type)
            summaries.setdefault(
                session.id,
                PeriodSessionSummary(
                    session.id,
                    session.name,
                    session.study_type_id,
                    name,
                    color,
                    self._local_datetime(session.created_at, zone).date(),
                    0,
                ),
            )
        total = sum(seconds_by_type.values())
        ranking = self._type_totals(seconds_by_type, metadata)
        buckets = tuple(
            ReportBucket(a, b, label, day, self._type_totals(values, metadata))
            for (a, b, label, day), values in zip(limits, per_bucket, strict=True)
        )
        today = self.get_today()
        average_days = max(0, (min(following, today + timedelta(days=1)) - first).days)
        filter_name = None
        if selection.type_filter == "untyped":
            filter_name = "Sem tipo"
        elif selection.type_filter == "type":
            assert selection.study_type_id is not None
            selected_type = self._repository.get_study_type(selection.study_type_id)
            filter_name = selected_type.name if selected_type else "Tipo indisponível"
        return PeriodReport(
            selection,
            first,
            following,
            start,
            end,
            total,
            total / average_days if average_days else 0.0,
            average_days,
            buckets,
            ranking,
            tuple(
                sorted(
                    summaries.values(),
                    key=lambda item: (
                        -item.duration_s,
                        unicodedata.normalize("NFKC", item.name).casefold(),
                        item.session_id,
                    ),
                )
            ),
            filter_name,
        )

    @staticmethod
    def _matches_type(selection: HistorySelection, type_id: int | None) -> bool:
        return (
            selection.type_filter == "all"
            or (selection.type_filter == "untyped" and type_id is None)
            or (selection.type_filter == "type" and type_id == selection.study_type_id)
        )

    @staticmethod
    def _type_metadata(study_type: StudyType | None) -> tuple[str, StudyColor | None]:
        return (study_type.name, study_type.color_key) if study_type else ("Sem tipo", None)

    @staticmethod
    def _type_totals(
        seconds: dict[int | None, int], metadata: dict[int | None, tuple[str, StudyColor | None]]
    ) -> tuple[StudyTypeTotal, ...]:
        total = sum(seconds.values())
        values = [
            StudyTypeTotal(
                type_id,
                metadata[type_id][0],
                metadata[type_id][1],
                value,
                value * 100.0 / total if total else 0.0,
            )
            for type_id, value in seconds.items()
            if value > 0
        ]
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    -item.duration_s,
                    unicodedata.normalize("NFKC", item.name).casefold(),
                    item.type_id if item.type_id is not None else -1,
                ),
            )
        )

    def _bucket_limits(
        self, period: ReportPeriod, first: date, following: date, zone: tzinfo
    ) -> list[tuple[int, int, str, date]]:
        if period == ReportPeriod.DAY:
            return self._hour_limits(first, following, zone)
        limits = []
        day = first
        weekdays = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
        while day < following:
            start, end = self._bounds(day, day + timedelta(days=1), zone)
            label = (
                f"{weekdays[day.weekday()]} {day.day}"
                if period == ReportPeriod.WEEK
                else str(day.day)
            )
            limits.append((start, end, label, day))
            day += timedelta(days=1)
        return limits

    def _hour_limits(
        self, first: date, following: date, zone: tzinfo
    ) -> list[tuple[int, int, str, date]]:
        start, end = self._bounds(first, following, zone)
        if start == end:
            return []
        boundaries = {start, end}
        for hour in range(24):
            naive = datetime.combine(first, time(hour))
            for fold in (0, 1):
                timestamp = int(naive.replace(tzinfo=zone, fold=fold).timestamp())
                # A conversão de volta rejeita uma hora local inexistente.
                if (
                    start < timestamp < end
                    and self._local_datetime(timestamp, zone).replace(tzinfo=None) == naive
                ):
                    boundaries.add(timestamp)
        # Uma mudança de offset também pode ocorrer às 02:30, fora das horas cheias.
        cursor = start
        while cursor < end - 1:
            probe = min(cursor + 1800, end - 1)
            offset = self._local_datetime(cursor, zone).utcoffset()
            if self._local_datetime(probe, zone).utcoffset() != offset:
                low, high = cursor, probe
                while high - low > 1:
                    middle = (low + high) // 2
                    if self._local_datetime(middle, zone).utcoffset() == offset:
                        low = middle
                    else:
                        high = middle
                boundaries.add(high)
            cursor = probe
        ordered = sorted(boundaries)
        local = [self._local_datetime(value, zone) for value in ordered[:-1]]
        repeated = Counter(value.hour for value in local)
        limits = []
        for a, b, value in zip(ordered[:-1], ordered[1:], local, strict=True):
            label = f"{value.hour:02d}h" + (f"{value.minute:02d}" if value.minute else "")
            if repeated[value.hour] > 1:
                offset_label = value.strftime("%z")
                label += f" UTC{offset_label[:3]}:{offset_label[3:]}"
            limits.append((a, b, label, first))
        return limits

    @staticmethod
    def _local_datetime(timestamp: int, zone: tzinfo) -> datetime:
        """Evita a faixa limitada de fromtimestamp do runtime Windows.

        Na primeira data local, UTC pode cair antes do ano 1 para offsets
        positivos. A zona ainda resolve o offset histórico dessa borda local.
        """
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        try:
            return (epoch + timedelta(seconds=timestamp)).astimezone(zone)
        except OverflowError:
            anchor = datetime(1, 1, 1, tzinfo=zone)
            offset = anchor.utcoffset()
            if offset is None:
                raise ValueError("Fuso sem offset válido.") from None
            local = datetime(1970, 1, 1) + timedelta(
                seconds=timestamp + int(offset.total_seconds())
            )
            return local.replace(tzinfo=zone)

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
        self._validate_report_snapshot(now)
        rows = self._repository.get_report_intervals(start, end, now.interval_id if now else None)
        segments = []
        for session, interval in rows:
            until = self._report_interval_end(interval, now)
            segments.append((session, interval.started_at, until))
        return segments

    @staticmethod
    def _validate_report_snapshot(now: ClockSnapshot | None) -> None:
        if now is not None and (
            now.elapsed_s < 0 or now.valid_until_utc_s != now.started_at + now.elapsed_s
        ):
            raise ValueError("Snapshot temporal inconsistente.")

    @staticmethod
    def _report_interval_end(interval: StudyInterval, now: ClockSnapshot | None) -> int:
        until = interval.ended_at if interval.ended_at is not None else interval.last_seen_at
        if now is not None and interval.ended_at is None and interval.id == now.interval_id:
            if now.started_at != interval.started_at or now.valid_until_utc_s < until:
                raise ValueError("Snapshot incompatível com o checkpoint.")
            until = now.valid_until_utc_s
        return until

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
