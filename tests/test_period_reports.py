"""Relatórios unificados por período/tipo com SQLite e fusos reais."""

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from time import perf_counter
from zoneinfo import ZoneInfo

import pytest

from app.database.repository import StudyRepository
from app.models import (
    ClockSnapshot,
    HistorySelection,
    PeriodReport,
    ReportPeriod,
    StudyColor,
)
from app.services.report_service import ReportService
from tests.test_reports import stamp


@pytest.fixture
def repository(connection: sqlite3.Connection) -> StudyRepository:
    return StudyRepository(connection)


@pytest.fixture
def reports(repository: StudyRepository, monkeypatch: pytest.MonkeyPatch) -> ReportService:
    service = ReportService(repository, lambda: UTC)
    monkeypatch.setattr(service, "get_today", lambda: date(2024, 5, 10))
    return service


def add(
    repository: StudyRepository,
    start: int,
    seconds: int,
    type_id: int | None = None,
    name: str = "Estudo",
) -> int:
    session, interval = repository.start_session(name, start, type_id)
    repository.finish_session(
        session.id, ClockSnapshot(interval.id, start, seconds, start + seconds)
    )
    return session.id


def conserved(report: PeriodReport) -> None:
    assert sum(item.duration_s for item in report.ranking) == report.total_s
    assert sum(bucket.duration_s for bucket in report.buckets) == report.total_s
    assert sum(item.duration_s for item in report.sessions) == report.total_s
    for left, right in zip(report.buckets, report.buckets[1:], strict=False):
        assert left.end_utc == right.start_utc
    if report.buckets:
        assert report.buckets[0].start_utc == report.start_utc
        assert report.buckets[-1].end_utc == report.end_utc


@pytest.mark.parametrize("period", list(ReportPeriod))
def test_totals_buckets_sessions_and_filters_conserve_seconds(
    repository: StudyRepository, reports: ReportService, period: ReportPeriod
) -> None:
    poo = repository.create_study_type("POO", StudyColor.BLUE)
    sql = repository.create_study_type("Banco de Dados", StudyColor.TEAL)
    add(repository, stamp(2024, 5, 10, 9), 35, poo.id, "A")
    add(repository, stamp(2024, 5, 10, 10), 35, poo.id, "B")
    add(repository, stamp(2024, 5, 10, 11), 30, sql.id)
    add(repository, stamp(2024, 5, 10, 12), 20)
    selection = HistorySelection(period, date(2024, 5, 10))
    report = reports.get_period_report(selection)
    assert report.total_s == 120
    assert [(row.name, row.duration_s) for row in report.ranking] == [
        ("POO", 70),
        ("Banco de Dados", 30),
        ("Sem tipo", 20),
    ]
    assert report.ranking[0].percentage == pytest.approx(70 / 120 * 100)
    conserved(report)
    for filtered, seconds in (
        (replace(selection, type_filter="type", study_type_id=poo.id), 70),
        (replace(selection, type_filter="untyped"), 20),
    ):
        result = reports.get_period_report(filtered)
        assert result.total_s == seconds
        assert result.average_days == report.average_days
        conserved(result)


def test_archived_renamed_types_keep_their_historical_identity(
    repository: StudyRepository, reports: ReportService
) -> None:
    item = repository.create_study_type("POO", StudyColor.BLUE)
    session_id = add(repository, stamp(2024, 5, 10, 12), 90, item.id)
    repository.set_study_type_archived(item.id, True)
    repository.update_study_type(item.id, "Objetos", StudyColor.PURPLE)
    result = reports.get_period_report(HistorySelection(ReportPeriod.DAY, date(2024, 5, 10)))
    assert result.ranking[0].name == "Objetos"
    assert result.ranking[0].color_key == StudyColor.PURPLE
    assert result.sessions[0].session_id == session_id
    assert result.sessions[0].type_name == "Objetos"
    conserved(result)


def test_live_snapshot_replaces_checkpoint_once_and_report_never_writes(
    repository: StudyRepository, connection: sqlite3.Connection, reports: ReportService
) -> None:
    start = stamp(2024, 5, 10, 23, 59)
    session, interval = repository.start_session("Ao vivo", start)
    repository.save_checkpoint(session.id, ClockSnapshot(interval.id, start, 30, start + 30))
    now = ClockSnapshot(interval.id, start, 90, start + 90)
    connection.execute("PRAGMA query_only = ON")
    first = reports.get_period_report(HistorySelection(ReportPeriod.DAY, date(2024, 5, 10)), now)
    following = reports.get_period_report(
        HistorySelection(ReportPeriod.DAY, date(2024, 5, 11)), now
    )
    assert first.total_s == 60 and following.total_s == 30
    assert first == reports.get_period_report(first.selection, now)
    conserved(first)
    conserved(following)
    assert repository.get_open_interval(session.id) == replace(interval, last_seen_at=start + 30)
    connection.execute("PRAGMA query_only = OFF")
    repository.pause_session(session.id, now)
    stale = replace(now, elapsed_s=3600, valid_until_utc_s=start + 3600)
    assert reports.get_period_report(first.selection, stale).total_s == 60


@pytest.mark.parametrize("part", ["elapsed", "end", "anchor", "regression"])
def test_invalid_active_snapshot_is_rejected_before_filtering(
    repository: StudyRepository, reports: ReportService, part: str
) -> None:
    start = stamp(2024, 5, 10, 12)
    session, interval = repository.start_session("Ativa", start)
    repository.save_checkpoint(session.id, ClockSnapshot(interval.id, start, 10, start + 10))
    now = ClockSnapshot(interval.id, start, 20, start + 20)
    if part == "elapsed":
        now = replace(now, elapsed_s=-1, valid_until_utc_s=start - 1)
    elif part == "end":
        now = replace(now, valid_until_utc_s=start + 19)
    elif part == "anchor":
        now = replace(now, started_at=start - 1, valid_until_utc_s=start + 19)
    else:
        now = replace(now, elapsed_s=9, valid_until_utc_s=start + 9)
    with pytest.raises(ValueError):
        reports.get_period_report(
            HistorySelection(ReportPeriod.MONTH, date(2024, 5, 10), "type", 999), now
        )


def test_zero_sessions_only_belong_to_creation_day(
    repository: StudyRepository, reports: ReportService
) -> None:
    start = stamp(2024, 5, 10, 12)
    session, first = repository.start_session("Zerada", start)
    repository.pause_session(session.id, ClockSnapshot(first.id, start, 0, start))
    _, second = repository.resume_session(session.id, start + 86400)
    repository.finish_session(session.id, ClockSnapshot(second.id, start + 86400, 0, start + 86400))
    result = reports.get_period_report(HistorySelection(ReportPeriod.DAY, date(2024, 5, 10)))
    assert result.total_s == 0 and not result.ranking
    assert len(result.sessions) == 1 and result.sessions[0].duration_s == 0
    assert not reports.get_period_report(
        HistorySelection(ReportPeriod.DAY, date(2024, 5, 11))
    ).sessions
    conserved(result)


def test_pauses_and_multiple_intervals_contribute_one_session(
    repository: StudyRepository, reports: ReportService
) -> None:
    start = stamp(2024, 5, 10, 12)
    session, first = repository.start_session("Pausas", start)
    repository.pause_session(session.id, ClockSnapshot(first.id, start, 35, start + 35))
    _, second = repository.resume_session(session.id, start + 3600)
    repository.finish_session(session.id, ClockSnapshot(second.id, start + 3600, 35, start + 3635))
    result = reports.get_period_report(HistorySelection(ReportPeriod.DAY, date(2024, 5, 10)))
    assert result.total_s == 70 and len(result.sessions) == 1
    conserved(result)


@pytest.mark.parametrize(
    ("period", "reference", "expected_days"),
    [
        (ReportPeriod.WEEK, date(2024, 5, 10), 5),
        (ReportPeriod.MONTH, date(2024, 5, 10), 10),
        (ReportPeriod.WEEK, date(2024, 4, 10), 7),
        (ReportPeriod.MONTH, date(2024, 2, 10), 29),
        (ReportPeriod.MONTH, date(2024, 6, 10), 0),
    ],
)
def test_average_uses_calendar_days_and_elapsed_current_period(
    reports: ReportService, period: ReportPeriod, reference: date, expected_days: int
) -> None:
    result = reports.get_period_report(HistorySelection(period, reference))
    assert result.average_days == expected_days and result.average_s == 0


def test_week_month_and_year_splits_are_half_open(
    repository: StudyRepository, reports: ReportService
) -> None:
    add(repository, stamp(2023, 12, 31, 23, 59), 120)
    previous = reports.get_period_report(HistorySelection(ReportPeriod.WEEK, date(2023, 12, 31)))
    following = reports.get_period_report(HistorySelection(ReportPeriod.MONTH, date(2024, 1, 1)))
    assert previous.start_day == date(2023, 12, 25)
    assert previous.end_day == date(2024, 1, 1)
    assert previous.total_s == following.total_s == 60
    conserved(previous)
    conserved(following)


def test_filtered_empty_period_uses_current_archived_type_name(
    repository: StudyRepository, reports: ReportService
) -> None:
    item = repository.create_study_type("POO", StudyColor.BLUE)
    repository.set_study_type_archived(item.id, True)
    selection = HistorySelection(ReportPeriod.MONTH, date(2024, 5, 10), "type", item.id)
    result = reports.get_period_report(selection)
    assert result.filter_name == "POO" and result.ranking == () and result.total_s == 0
    repository.update_study_type(item.id, "Objetos", StudyColor.PURPLE)
    assert reports.get_period_report(selection).filter_name == "Objetos"
    assert (
        reports.get_period_report(
            replace(selection, type_filter="untyped", study_type_id=None)
        ).filter_name
        == "Sem tipo"
    )


def test_average_preserves_fractional_seconds_and_zero_study_days(
    repository: StudyRepository, reports: ReportService
) -> None:
    add(repository, stamp(2024, 5, 10, 12), 35)
    result = reports.get_period_report(HistorySelection(ReportPeriod.MONTH, date(2024, 5, 10)))
    assert result.total_s == 35 and result.average_days == 10 and result.average_s == 3.5


def test_session_date_tracks_first_contribution_in_selected_period(
    repository: StudyRepository, reports: ReportService
) -> None:
    add(repository, stamp(2024, 4, 30, 23, 50), 1800)
    result = reports.get_period_report(HistorySelection(ReportPeriod.MONTH, date(2024, 5, 1)))
    assert result.total_s == 1200 and result.sessions[0].day == date(2024, 5, 1)
    conserved(result)


@pytest.mark.parametrize(
    ("zone_name", "day", "seconds"),
    [
        ("America/New_York", date(2024, 3, 10), 23 * 3600),
        ("America/New_York", date(2024, 11, 3), 25 * 3600),
        ("America/Sao_Paulo", date(2018, 11, 4), 23 * 3600),
        ("America/Havana", date(2020, 11, 1), 25 * 3600),
        ("Australia/Lord_Howe", date(2024, 10, 6), 23 * 3600 + 1800),
        ("Australia/Lord_Howe", date(2024, 4, 7), 24 * 3600 + 1800),
        ("Pacific/Apia", date(2011, 12, 30), 0),
    ],
)
def test_hourly_buckets_respect_dst_half_hour_and_skipped_days(
    repository: StudyRepository, zone_name: str, day: date, seconds: int
) -> None:
    zone = ZoneInfo(zone_name)
    start = int(datetime.combine(day, datetime.min.time(), zone).timestamp())
    if seconds:
        add(repository, start, seconds)
    service = ReportService(repository, lambda: zone)
    result = service.get_period_report(HistorySelection(ReportPeriod.DAY, day))
    assert result.total_s == seconds
    assert sum(bucket.end_utc - bucket.start_utc for bucket in result.buckets) == seconds
    assert all(bucket.end_utc - bucket.start_utc <= 3600 for bucket in result.buckets)
    assert len({bucket.label for bucket in result.buckets}) == len(result.buckets)
    if zone_name == "Australia/Lord_Howe" and seconds:
        assert any(bucket.end_utc - bucket.start_utc == 1800 for bucket in result.buckets)
    if seconds > 86400:
        assert any("UTC" in bucket.label for bucket in result.buckets)
    conserved(result)


def test_timezone_is_reloaded_for_new_queries(repository: StudyRepository) -> None:
    add(repository, stamp(2024, 5, 10, 1), 3600)
    zones = [ZoneInfo("UTC")]
    reports = ReportService(repository, lambda: zones[0])
    selection = HistorySelection(ReportPeriod.DAY, date(2024, 5, 10))
    assert reports.get_period_report(selection).total_s == 3600
    zones[0] = ZoneInfo("America/Fortaleza")
    assert reports.get_period_report(selection).total_s == 0
    assert reports.get_period_report(replace(selection, reference=date(2024, 5, 9))).total_s == 3600


@pytest.mark.parametrize("reference", [date(1, 1, 1), date(9998, 12, 31)])
@pytest.mark.parametrize("period", list(ReportPeriod))
@pytest.mark.parametrize("zone_name", ["UTC", "Etc/GMT-14"])
def test_supported_date_limits_remain_queryable(
    repository: StudyRepository, reference: date, period: ReportPeriod, zone_name: str
) -> None:
    reports = ReportService(repository, lambda: ZoneInfo(zone_name))
    result = reports.get_period_report(HistorySelection(period, reference))
    assert result.total_s == 0
    conserved(result)


def test_ties_and_many_types_have_deterministic_order_and_two_selects(
    connection: sqlite3.Connection, repository: StudyRepository, reports: ReportService
) -> None:
    for index in range(20):
        item = repository.create_study_type(
            f"Tipo {index:02}", StudyColor(list(StudyColor)[index % 8])
        )
        add(repository, stamp(2024, 5, 10, 12), 35, item.id)
    queries: list[str] = []
    connection.set_trace_callback(queries.append)
    try:
        result = reports.get_period_report(HistorySelection(ReportPeriod.MONTH, date(2024, 5, 10)))
    finally:
        connection.set_trace_callback(None)
    assert len([sql for sql in queries if sql.lstrip().upper().startswith("SELECT")]) == 2
    assert [row.name for row in result.ranking] == [f"Tipo {index:02}" for index in range(20)]
    conserved(result)


def test_thousand_sessions_query_and_buckets_under_two_seconds(
    connection: sqlite3.Connection, repository: StudyRepository, reports: ReportService
) -> None:
    start = stamp(2024, 5, 10, 12)
    with repository.transaction() as database:
        database.executemany(
            "INSERT INTO sessions (id,name,created_at,finished_at,status) VALUES (?,?,?,?,?)",
            [(index, "Desempenho", start, start + 35, "finished") for index in range(1, 1001)],
        )
        database.executemany(
            "INSERT INTO study_intervals VALUES (?,?,?,?,?)",
            [(index, index, start, start + 35, start + 35) for index in range(1, 1001)],
        )
    began = perf_counter()
    result = reports.get_period_report(HistorySelection(ReportPeriod.MONTH, date(2024, 5, 10)))
    elapsed = perf_counter() - began
    assert elapsed < 2
    assert result.total_s == 35000 and len(result.sessions) == 1000
    conserved(result)
    print(f"Relatório unificado de 1000 sessões: {elapsed:.3f}s")
