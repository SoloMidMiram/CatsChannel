"""Explicit, offline scheduling of the existing one-shot discovery scanner."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .scanner import OneShotScanner, ScanReport

_INTERVAL = timedelta(hours=4)


@dataclass(frozen=True)
class ScheduledScan:
    scheduled_at: datetime
    channels: tuple[ScanReport, ...]


class ScheduledScanError(RuntimeError):
    """A slot failed after earlier slots in the same tick returned reports."""

    def __init__(self, failed_at: datetime, completed: tuple[ScheduledScan, ...]):
        super().__init__(f"Scheduled scan failed for {failed_at.isoformat()}")
        self.failed_at = failed_at
        self.completed = completed


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("scheduler_requires_aware_datetime")
    return value.astimezone(UTC)


class OfflineDiscoveryScheduler:
    """Run due slots under one scheduler instance on one event loop.

    The caller supplies the first UTC slot, or the last saved next_due when
    reconstructing the scheduler. The scanner owns durable channel progress.
    """

    def __init__(
        self,
        scanner: OneShotScanner,
        *,
        clock: Callable[[], datetime],
        first_slot: datetime,
        max_runs_per_tick: int = 2,
    ):
        first_slot = _utc(first_slot)
        if first_slot.hour % 4 or first_slot.minute or first_slot.second or first_slot.microsecond:
            raise ValueError("scheduler_requires_four_hour_boundary")
        if type(max_runs_per_tick) is not int or max_runs_per_tick < 1:
            raise ValueError("invalid_scheduler_run_limit")
        self._scanner = scanner
        self._clock = clock
        self._next_due = first_slot
        self._max_runs_per_tick = max_runs_per_tick
        self._running = False

    @property
    def next_due(self) -> datetime:
        """Oldest pending UTC slot, including any interrupted slot."""
        return self._next_due

    async def run_due(self, *, enabled: bool) -> tuple[ScheduledScan, ...]:
        """Attempt due slots in order. Leave excess backlog for a later call.

        Concurrent calls return immediately. Partial channel reports consume a
        scheduled attempt. An exception or cancellation leaves that slot due,
        so a retry uses the same cycle and can resume durable scanner progress.
        If a scan fails after earlier slots returned reports, ScheduledScanError
        carries those reports and chains the original exception. Cancellation
        propagates directly.
        """
        if not enabled or self._running:
            return ()
        self._running = True
        try:
            now = _utc(self._clock())
            reports = []
            for _ in range(self._max_runs_per_tick):
                slot = self._next_due
                if slot > now:
                    break
                try:
                    channels = await self._scanner.scan(cycle=slot.strftime("scheduled-%Y%m%dT%HZ"))
                except Exception as error:
                    if not reports:
                        raise
                    raise ScheduledScanError(slot, tuple(reports)) from error
                self._next_due = slot + _INTERVAL
                reports.append(ScheduledScan(slot, channels))
            return tuple(reports)
        finally:
            self._running = False
