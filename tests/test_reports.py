"""Calendário local, DST, agregação e snapshots sobre SQLite temporário real."""

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from zoneinfo import ZoneInfo

import pytest

from app.database.repository import StudyRepository
from app.models import ClockSnapshot
from app.services.report_service import ReportService


def add_interval(
    repository: StudyRepository, start: int, seconds: int, name: str = "Estudo"
) -> int:
    session, interval = repository.start_session(name, start)
    repository.finish_session(
        session.id, ClockSnapshot(interval.id, start, seconds, start + seconds)
    )
    return session.id


def stamp(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


@pytest.fixture
def repository(connection: sqlite3.Connection) -> StudyRepository:
    return StudyRepository(connection)


@pytest.fixture
def reports(repository: StudyRepository) -> ReportService:
    return ReportService(repository, lambda: UTC)


def test_aggregate_seconds_before_truncating_minutes(
    repository: StudyRepository, reports: ReportService
) -> None:
    add_interval(repository, stamp(2024, 5, 10, 12), 35, "A")
    add_interval(repository, stamp(2024, 5, 10, 13), 35, "B")
    totals = reports.get_totals(date(2024, 5, 10), None)
    assert totals.today_s == totals.week_s == totals.month_s == 70
    assert totals.today_s // 60 == 1
    assert sum(s.duration_s for s in reports.get_day_sessions(date(2024, 5, 10), None)) == 70


def test_midnight_month_leap_day_and_half_open_boundaries(
    repository: StudyRepository, reports: ReportService
) -> None:
    add_interval(repository, stamp(2024, 2, 29, 23, 30), 3600)
    feb = reports.get_month_days(2024, 2, None)
    march = reports.get_month_days(2024, 3, None)
    assert len(feb) == 29 and feb[date(2024, 2, 29)] == 1800
    assert len(march) == 31 and march[date(2024, 3, 1)] == 1800
    assert reports.get_totals(date(2024, 3, 1), None).month_s == 1800
    assert reports.get_day_sessions(date(2024, 3, 2), None) == []


def test_week_starts_monday_even_across_years(
    repository: StudyRepository, reports: ReportService
) -> None:
    add_interval(repository, stamp(2023, 12, 31, 23, 59), 120)
    assert reports.get_totals(date(2023, 12, 31), None).week_s == 60
    totals = reports.get_totals(date(2024, 1, 1), None)
    assert totals.today_s == totals.week_s == totals.month_s == 60
    assert reports.get_totals(date(2024, 1, 7), None).week_s == 60
    assert reports.get_totals(date(2024, 1, 8), None).week_s == 0


def test_snapshot_replaces_checkpoint_once_and_is_never_written(
    repository: StudyRepository, reports: ReportService
) -> None:
    start = stamp(2024, 12, 31, 23, 59)
    session, interval = repository.start_session("Ativa", start)
    repository.save_checkpoint(session.id, ClockSnapshot(interval.id, start, 30, start + 30))
    snapshot = ClockSnapshot(interval.id, start, 90, start + 90)
    for _ in range(2):
        assert reports.get_totals(date(2024, 12, 31), snapshot).today_s == 60
        assert reports.get_month_days(2025, 1, snapshot)[date(2025, 1, 1)] == 30
        assert reports.get_day_sessions(date(2025, 1, 1), snapshot)[0].duration_s == 30
    assert reports.get_totals(date(2024, 12, 31), None).today_s == 30
    assert repository.get_open_interval(session.id) == replace(interval, last_seen_at=start + 30)
    repository.pause_session(session.id, snapshot)
    # Um snapshot antigo para um intervalo já fechado nunca estende o histórico.
    stale = replace(snapshot, elapsed_s=3600, valid_until_utc_s=start + 3600)
    assert reports.get_totals(date(2025, 1, 1), stale).today_s == 30


@pytest.mark.parametrize("part", ["elapsed", "end", "anchor", "regression"])
def test_invalid_active_snapshots_are_rejected(
    repository: StudyRepository, reports: ReportService, part: str
) -> None:
    start = stamp(2024, 5, 10)
    session, interval = repository.start_session("Snapshot", start)
    repository.save_checkpoint(session.id, ClockSnapshot(interval.id, start, 5, start + 5))
    snapshot = ClockSnapshot(interval.id, start, 10, start + 10)
    if part == "elapsed":
        snapshot = replace(snapshot, elapsed_s=-1, valid_until_utc_s=start - 1)
    elif part == "end":
        snapshot = replace(snapshot, valid_until_utc_s=start + 9)
    elif part == "anchor":
        snapshot = replace(snapshot, started_at=start - 1, valid_until_utc_s=start + 9)
    else:
        snapshot = replace(snapshot, elapsed_s=3, valid_until_utc_s=start + 3)
    with pytest.raises(ValueError):
        reports.get_totals(date(2024, 5, 10), snapshot)


def test_multiple_intervals_of_one_session_are_merged_and_pauses_excluded(
    repository: StudyRepository, reports: ReportService
) -> None:
    start = stamp(2024, 5, 10)
    session, interval = repository.start_session("Mesma sessão", start)
    repository.pause_session(session.id, ClockSnapshot(interval.id, start, 35, start + 35))
    _, interval = repository.resume_session(session.id, start + 3600)
    repository.finish_session(
        session.id, ClockSnapshot(interval.id, start + 3600, 35, start + 3635)
    )
    summaries = reports.get_day_sessions(date(2024, 5, 10), None)
    assert len(summaries) == 1 and summaries[0].duration_s == 70


def test_zero_second_sessions_belong_only_to_their_creation_day(
    repository: StudyRepository, reports: ReportService
) -> None:
    start = stamp(2024, 5, 10)
    session, first = repository.start_session("Sem tempo", start)
    repository.pause_session(session.id, ClockSnapshot(first.id, start, 0, start))
    _, later = repository.resume_session(session.id, start + 86400)
    repository.finish_session(session.id, ClockSnapshot(later.id, start + 86400, 0, start + 86400))
    zero = reports.get_day_sessions(date(2024, 5, 10), None)
    assert len(zero) == 1 and zero[0].duration_s == 0
    assert reports.get_day_sessions(date(2024, 5, 11), None) == []


def test_live_session_with_positive_snapshot_is_not_also_a_zero_session(
    repository: StudyRepository, reports: ReportService
) -> None:
    start = stamp(2024, 5, 10, 23, 59)
    _, interval = repository.start_session("Ativa", start)
    now = ClockSnapshot(interval.id, start, 120, start + 120)
    assert reports.get_day_sessions(date(2024, 5, 10), now)[0].duration_s == 60
    assert reports.get_day_sessions(date(2024, 5, 11), now)[0].duration_s == 60


@pytest.mark.parametrize(
    ("zone_name", "day", "hours"),
    [
        ("America/New_York", date(2024, 3, 10), 23),
        ("America/New_York", date(2024, 11, 3), 25),
        ("America/Sao_Paulo", date(2018, 11, 4), 23),
        ("America/Havana", date(2020, 11, 1), 25),
        ("Australia/Lord_Howe", date(2024, 10, 6), 23.5),
    ],
)
def test_local_day_duration_uses_historical_dst_boundaries(
    repository: StudyRepository, zone_name: str, day: date, hours: float
) -> None:
    zone = ZoneInfo(zone_name)
    start = int(datetime(day.year, day.month, day.day, tzinfo=zone).timestamp())
    add_interval(repository, start, int(hours * 3600))
    reports = ReportService(repository, lambda: zone)
    totals = reports.get_totals(day, None)
    assert totals.today_s == int(hours * 3600)
    month = reports.get_month_days(day.year, day.month, None)
    assert month[day] == int(hours * 3600) and sum(month.values()) == int(hours * 3600)
    assert reports.get_day_sessions(day, None)[0].duration_s == int(hours * 3600)
    assert reports.get_day_sessions(day + timedelta(days=1), None) == []


def test_repeated_hour_is_counted_twice_in_real_elapsed_time(repository: StudyRepository) -> None:
    zone = ZoneInfo("America/New_York")
    first = datetime(2024, 11, 3, 1, 30, tzinfo=zone, fold=0)
    second = first.replace(fold=1)
    start, end = int(first.timestamp()), int(second.timestamp())
    add_interval(repository, start, end - start)
    reports = ReportService(repository, lambda: zone)
    assert reports.get_totals(date(2024, 11, 3), None).today_s == 3600


def test_skipped_local_date_has_zero_seconds(repository: StudyRepository) -> None:
    zone = ZoneInfo("Pacific/Apia")
    start = int(datetime(2011, 12, 29, tzinfo=zone).timestamp())
    add_interval(repository, start, 48 * 3600)
    days = ReportService(repository, lambda: zone).get_month_days(2011, 12, None)
    assert days[date(2011, 12, 29)] == days[date(2011, 12, 31)] == 24 * 3600
    assert days[date(2011, 12, 30)] == 0


def test_timezone_is_resolved_again_and_redistributes_history(repository: StudyRepository) -> None:
    add_interval(repository, stamp(2024, 5, 10, 1), 3600)
    zones = [ZoneInfo("UTC")]
    reports = ReportService(repository, lambda: zones[0])
    assert reports.get_totals(date(2024, 5, 10), None).today_s == 3600
    zones[0] = ZoneInfo("America/Fortaleza")
    assert reports.get_totals(date(2024, 5, 10), None).today_s == 0
    assert reports.get_totals(date(2024, 5, 9), None).today_s == 3600


def test_selected_month_does_not_change_current_period_cards(
    repository: StudyRepository, reports: ReportService
) -> None:
    add_interval(repository, stamp(2024, 5, 10), 70)
    add_interval(repository, stamp(2024, 4, 10), 120)
    before = reports.get_totals(date(2024, 5, 10), None)
    assert sum(reports.get_month_days(2024, 4, None).values()) == 120
    assert reports.get_totals(date(2024, 5, 10), None) == before


def test_thousand_sessions_report_within_two_seconds(
    connection: sqlite3.Connection, repository: StudyRepository, reports: ReportService
) -> None:
    start = stamp(2024, 5, 10)
    with repository.transaction() as database:
        database.executemany(
            "INSERT INTO sessions (id, name, created_at, finished_at, status) "
            "VALUES (?, ?, ?, ?, ?)",
            [(i, "Teste de desempenho", start, start + 35, "finished") for i in range(1, 1001)],
        )
        database.executemany(
            "INSERT INTO study_intervals VALUES (?, ?, ?, ?, ?)",
            [(i, i, start, start + 35, start + 35) for i in range(1, 1001)],
        )
    began = perf_counter()
    totals = reports.get_totals(date(2024, 5, 10), None)
    days = reports.get_month_days(2024, 5, None)
    sessions = reports.get_day_sessions(date(2024, 5, 10), None)
    elapsed = perf_counter() - began
    assert totals.today_s == days[date(2024, 5, 10)] == 35000
    assert len(sessions) == 1000
    assert elapsed < 2, f"Consultas levaram {elapsed:.3f}s"
    print(f"Relatórios de 1000 sessões: {elapsed:.3f}s")
