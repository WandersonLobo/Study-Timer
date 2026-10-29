"""Valida o relógio com amostras determinísticas, sem esperas ou interface."""

import logging
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from app.models import ClockReading, ClockSnapshot, PauseReason
from app.services.clock_service import ClockService, SystemClock

SECOND_NS = 1_000_000_000


@dataclass
class FakeClock:
    """Permite controlar separadamente tempo civil, monotônico e falhas da fonte."""

    wall_time_s: float = 1_800_000_000.75
    monotonic_ns: int = 100 * SECOND_NS
    read_count: int = 0
    failure: Exception | None = None

    def read(self) -> ClockReading:
        """Retorna a amostra atual sem avançar o tempo automaticamente."""
        self.read_count += 1
        if self.failure is not None:
            raise self.failure
        return ClockReading(self.wall_time_s, self.monotonic_ns)

    def advance(self, delta_ns: int, wall_delta_s: float | None = None) -> None:
        """Avança os relógios juntos ou aplica um deslocamento civil independente."""
        self.monotonic_ns += delta_ns
        self.wall_time_s += delta_ns / SECOND_NS if wall_delta_s is None else wall_delta_s


@pytest.fixture
def source() -> FakeClock:
    return FakeClock()


@pytest.fixture
def clock(source: FakeClock) -> ClockService:
    return ClockService(source)


def test_idle_clock_does_not_sample_or_create_snapshots(
    clock: ClockService, source: FakeClock
) -> None:
    assert clock.get_snapshot() is None
    assert clock.tick() is None
    assert clock.pause() is None
    clock.reset()
    assert not clock.is_running
    assert clock.pause_reason is None
    assert source.read_count == 0


def test_start_captures_one_utc_anchor(clock: ClockService, source: FakeClock) -> None:
    snapshot = clock.start_interval(7)
    assert snapshot == ClockSnapshot(7, 1_800_000_000, 0, 1_800_000_000)
    assert clock.get_snapshot() is snapshot
    assert clock.is_running
    assert clock.pause_reason is None
    assert source.read_count == 1


def test_transaction_can_reuse_the_exact_captured_anchor(
    clock: ClockService, source: FakeClock
) -> None:
    anchor = clock.capture_anchor()
    source.advance(750_000_000)
    initial = clock.start_interval(7, anchor)
    assert source.read_count == 1
    assert initial.started_at == int(anchor.wall_time_s)
    source.advance(250_000_000)
    assert clock.tick() == ClockSnapshot(7, initial.started_at, 1, initial.started_at + 1)


def test_fractional_ticks_are_aggregated_before_truncation(
    clock: ClockService, source: FakeClock
) -> None:
    initial = clock.start_interval(7)
    elapsed_ns = 0
    for delta_ns in (249_999_999, 250_000_001, 333_333_333, 166_666_667):
        source.advance(delta_ns)
        elapsed_ns += delta_ns
        snapshot = clock.tick()
        assert snapshot is not None
        assert snapshot.elapsed_s == elapsed_ns // SECOND_NS
        assert snapshot.valid_until_utc_s == initial.started_at + snapshot.elapsed_s
    assert initial.elapsed_s == 0
    assert snapshot is not None and snapshot.elapsed_s == 1


def test_many_irregular_callbacks_do_not_accumulate_rounding_drift(
    clock: ClockService, source: FakeClock
) -> None:
    clock.start_interval(7)
    for _ in range(3000):
        source.advance(333_333_333)
        clock.tick()
    snapshot = clock.get_snapshot()
    assert snapshot is not None
    assert snapshot.elapsed_s == (3000 * 333_333_333) // SECOND_NS == 999
    assert clock.is_running


@pytest.mark.parametrize("origin", [-(2**60), 0, 2**60])
def test_monotonic_origin_is_arbitrary_and_keeps_integer_precision(
    source: FakeClock, clock: ClockService, origin: int
) -> None:
    source.monotonic_ns = origin
    clock.start_interval(7)
    source.advance(SECOND_NS - 1)
    snapshot = clock.tick()
    assert snapshot is not None and snapshot.elapsed_s == 0
    source.advance(1)
    snapshot = clock.tick()
    assert snapshot is not None and snapshot.elapsed_s == 1


def test_reading_snapshots_cannot_mask_a_gap(clock: ClockService, source: FakeClock) -> None:
    initial = clock.start_interval(7)
    source.advance(60 * SECOND_NS)
    for _ in range(10):
        assert clock.get_snapshot() is initial
    # Uma leitura de diagnóstico também não confirma ticks.
    clock.capture_anchor()
    assert clock.tick() is initial
    assert clock.pause_reason == PauseReason.TICK_GAP
    assert not clock.is_running


@pytest.mark.parametrize(
    ("delta_ns", "rejected"),
    [(5 * SECOND_NS, False), (5 * SECOND_NS + 1, True), (3600 * SECOND_NS, True)],
)
def test_gap_threshold_preserves_the_last_valid_tick(
    clock: ClockService, source: FakeClock, delta_ns: int, rejected: bool
) -> None:
    clock.start_interval(7)
    source.advance(SECOND_NS)
    previous = clock.tick()
    source.advance(delta_ns)
    snapshot = clock.tick()
    assert clock.is_running is not rejected
    if rejected:
        assert snapshot is previous
        assert snapshot is not None and snapshot.elapsed_s == 1
        assert clock.pause_reason == PauseReason.TICK_GAP
    else:
        assert snapshot is not None and snapshot.elapsed_s == 6
        assert clock.pause_reason is None


@pytest.mark.parametrize("jump_s", [-3600.0, -5.001, -5.0, 5.0, 5.001, 3600.0])
def test_wall_clock_changes_never_supply_elapsed_time(
    clock: ClockService, source: FakeClock, jump_s: float
) -> None:
    initial = clock.start_interval(7)
    source.advance(SECOND_NS)
    previous = clock.tick()
    source.advance(SECOND_NS, wall_delta_s=1.0 + jump_s)
    snapshot = clock.tick()
    assert snapshot is not None
    assert snapshot.valid_until_utc_s >= initial.started_at
    if abs(jump_s) > 5:
        assert snapshot is previous
        assert not clock.is_running
        assert clock.pause_reason == PauseReason.CLOCK_CHANGE
    else:
        assert clock.is_running
        assert snapshot.elapsed_s == 2
        assert snapshot.valid_until_utc_s == initial.started_at + 2


def test_gradual_civil_slew_is_compared_between_successive_readings(
    clock: ClockService, source: FakeClock
) -> None:
    initial = clock.start_interval(7)
    for _ in range(40):
        source.advance(250_000_000, wall_delta_s=0.5)
        clock.tick()
    snapshot = clock.get_snapshot()
    assert snapshot is not None
    assert clock.is_running
    assert snapshot.elapsed_s == 10
    assert snapshot.valid_until_utc_s == initial.started_at + 10


def test_monotonic_regression_freezes_without_negative_duration(
    clock: ClockService, source: FakeClock
) -> None:
    clock.start_interval(7)
    source.advance(SECOND_NS)
    previous = clock.tick()
    source.advance(-1, wall_delta_s=0.25)
    assert clock.tick() is previous
    assert not clock.is_running
    assert clock.pause_reason == PauseReason.CLOCK_CHANGE


@pytest.mark.parametrize("monotonic_advance_ns", [0, 3600 * SECOND_NS])
def test_suspend_is_excluded_whether_the_monotonic_source_advances_or_stops(
    clock: ClockService, source: FakeClock, monotonic_advance_ns: int
) -> None:
    clock.start_interval(7)
    source.advance(SECOND_NS)
    previous = clock.tick()
    source.advance(monotonic_advance_ns, wall_delta_s=3600.0)
    assert clock.tick() is previous
    assert previous is not None and previous.elapsed_s == 1
    assert not clock.is_running
    source.advance(SECOND_NS)
    assert clock.tick() is previous


@pytest.mark.parametrize("reason", list(PauseReason))
def test_pause_never_samples_and_remains_frozen_until_explicit_start(
    clock: ClockService, source: FakeClock, reason: PauseReason
) -> None:
    clock.start_interval(7)
    source.advance(SECOND_NS)
    previous = clock.tick()
    read_count = source.read_count
    source.advance(3 * SECOND_NS)
    assert clock.pause(reason) is previous
    source.advance(3600 * SECOND_NS)
    assert clock.tick() is previous
    assert clock.pause(PauseReason.USER) is previous
    assert source.read_count == read_count
    assert not clock.is_running
    assert clock.pause_reason == reason


def test_new_interval_uses_a_new_anchor_and_excludes_paused_time(
    clock: ClockService, source: FakeClock
) -> None:
    previous = clock.start_interval(7)
    source.advance(2 * SECOND_NS)
    clock.tick()
    clock.pause()
    source.advance(3600 * SECOND_NS)
    current = clock.start_interval(8)
    assert current.interval_id == 8
    assert current.elapsed_s == 0
    assert current.started_at == int(source.wall_time_s)
    assert clock.pause_reason is None
    source.advance(SECOND_NS)
    snapshot = clock.tick()
    assert snapshot is not None and snapshot.elapsed_s == 1
    assert previous.elapsed_s == 0


def test_active_interval_cannot_be_replaced_or_reset(
    clock: ClockService, source: FakeClock
) -> None:
    previous = clock.start_interval(7)
    with pytest.raises(RuntimeError):
        clock.start_interval(8)
    with pytest.raises(RuntimeError):
        clock.reset()
    assert clock.get_snapshot() is previous
    assert source.read_count == 1
    assert clock.is_running


def test_reset_clears_a_stopped_interval(clock: ClockService) -> None:
    clock.start_interval(7)
    clock.pause()
    clock.reset()
    assert clock.get_snapshot() is None
    assert clock.pause_reason is None
    assert not clock.is_running


@pytest.mark.parametrize("interval_id", [0, -1])
def test_invalid_identifier_does_not_start_or_sample(
    clock: ClockService, source: FakeClock, interval_id: int
) -> None:
    with pytest.raises(ValueError):
        clock.start_interval(interval_id)
    assert clock.get_snapshot() is None
    assert not clock.is_running
    assert source.read_count == 0


@pytest.mark.parametrize("wall_time_s", [float("nan"), float("inf"), float("-inf")])
def test_invalid_anchor_does_not_change_state(
    clock: ClockService, source: FakeClock, wall_time_s: float
) -> None:
    source.wall_time_s = wall_time_s
    with pytest.raises(ValueError):
        clock.start_interval(7)
    assert clock.get_snapshot() is None
    assert not clock.is_running
    with pytest.raises(ValueError):
        clock.start_interval(7, ClockReading(wall_time_s, 0))


@pytest.mark.parametrize("wall_time_s", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_tick_freezes_before_reporting_invalid_source(
    clock: ClockService, source: FakeClock, wall_time_s: float
) -> None:
    previous = clock.start_interval(7)
    source.wall_time_s = wall_time_s
    with pytest.raises(ValueError):
        clock.tick()
    assert clock.get_snapshot() is previous
    assert not clock.is_running
    assert clock.pause_reason == PauseReason.CLOCK_CHANGE


def test_source_failure_freezes_before_propagating_without_logging_private_text(
    clock: ClockService, source: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    previous = clock.start_interval(7)
    private_text = "Sessão particular em C:/Users/UsuarioPrivado"
    source.failure = OSError(private_text)
    with (
        patch.object(logging.getLogger("studytimer"), "propagate", True),
        caplog.at_level(logging.WARNING),
        pytest.raises(OSError),
    ):
        clock.tick()
    assert not clock.is_running
    assert clock.pause_reason == PauseReason.CLOCK_CHANGE
    assert clock.get_snapshot() is previous
    assert "CLOCK_SOURCE_FAILED type=OSError" in caplog.text
    assert private_text not in caplog.text
    source.failure = None
    source.advance(10 * SECOND_NS)
    assert clock.tick() is previous


def test_system_clock_captures_wall_then_monotonic_in_one_read() -> None:
    calls: list[str] = []

    def wall_sample() -> float:
        calls.append("wall")
        return 1_800_000_000.75

    def monotonic_sample() -> int:
        calls.append("monotonic")
        return 123_456_789

    with (
        patch("app.services.clock_service.time.time", side_effect=wall_sample),
        patch("app.services.clock_service.time.monotonic_ns", side_effect=monotonic_sample),
    ):
        reading = SystemClock().read()
    assert reading == ClockReading(1_800_000_000.75, 123_456_789)
    assert calls == ["wall", "monotonic"]
