"""Offline scheduler behavior with deterministic clocks and synthetic scans."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cats_channel.discovery.scanner import ScanReport
from cats_channel.discovery.scheduler import OfflineDiscoveryScheduler, ScheduledScanError

START = datetime(2026, 11, 15, tzinfo=UTC)
INTERVAL = timedelta(hours=4)


class Clock:
    now = START

    def __call__(self):
        return self.now


class RecordingScanner:
    def __init__(self):
        self.cycles = []

    async def scan(self, *, cycle):
        self.cycles.append(cycle)
        return ()


async def test_utc_cadence_and_disabled_tick():
    clock = Clock()
    scanner = RecordingScanner()
    scheduler = OfflineDiscoveryScheduler(scanner, clock=clock, first_slot=START)
    for index in range(6):
        slot = START + index * INTERVAL
        clock.now = slot - timedelta(microseconds=1)
        assert await scheduler.run_due(enabled=True) == ()
        clock.now = slot
        assert await scheduler.run_due(enabled=False) == ()
        [run] = await scheduler.run_due(enabled=True)
        assert run.scheduled_at == slot
        assert await scheduler.run_due(enabled=True) == ()
    assert scanner.cycles == [f"scheduled-20261115T{hour:02}Z" for hour in range(0, 24, 4)]
    assert scheduler.next_due == START + timedelta(days=1)


async def test_downtime_catch_up_is_bounded_and_preserves_backlog():
    clock = Clock()
    clock.now = START + 4 * INTERVAL
    scheduler = OfflineDiscoveryScheduler(RecordingScanner(), clock=clock, first_slot=START)
    for indices in (range(2), range(2, 4), range(4, 5)):
        runs = await scheduler.run_due(enabled=True)
        assert [run.scheduled_at for run in runs] == [START + i * INTERVAL for i in indices]
    assert await scheduler.run_due(enabled=True) == ()
    assert scheduler.next_due == START + 5 * INTERVAL


async def test_overlapping_tick_returns_and_cancellation_releases_execution():
    entered = asyncio.Event()
    released = asyncio.Event()

    class BlockingScanner(RecordingScanner):
        async def scan(self, *, cycle):
            await super().scan(cycle=cycle)
            entered.set()
            await released.wait()
            return ()

    scanner = BlockingScanner()
    scheduler = OfflineDiscoveryScheduler(scanner, clock=Clock(), first_slot=START)
    task = asyncio.create_task(scheduler.run_due(enabled=True))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert await asyncio.wait_for(scheduler.run_due(enabled=True), timeout=5) == ()
        assert len(scanner.cycles) == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert scheduler.next_due == START
    released.set()
    [run] = await scheduler.run_due(enabled=True)
    assert run.scheduled_at == START
    assert scanner.cycles == ["scheduled-20261115T00Z"] * 2


async def test_second_slot_failure_reports_first_slot_and_retries_only_the_second():
    channels = (ScanReport("fixture-channel", "completed", None, items=10),)

    class FailingScanner(RecordingScanner):
        async def scan(self, *, cycle):
            await super().scan(cycle=cycle)
            if len(self.cycles) == 2:
                raise OSError("fixture storage unavailable")
            return channels

    clock = Clock()
    clock.now = START + INTERVAL
    scanner = FailingScanner()
    scheduler = OfflineDiscoveryScheduler(scanner, clock=clock, first_slot=START)
    with pytest.raises(ScheduledScanError) as failure:
        await scheduler.run_due(enabled=True)
    assert failure.value.failed_at == START + INTERVAL
    assert isinstance(failure.value.__cause__, OSError)
    assert str(failure.value.__cause__) == "fixture storage unavailable"
    [completed] = failure.value.completed
    assert completed.scheduled_at == START
    assert completed.channels == channels
    assert scheduler.next_due == START + INTERVAL
    [run] = await scheduler.run_due(enabled=True)
    assert run.scheduled_at == START + INTERVAL
    assert scanner.cycles == [
        "scheduled-20261115T00Z",
        "scheduled-20261115T04Z",
        "scheduled-20261115T04Z",
    ]
