"""One-shot orchestration for the offline discovery ledger."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .domain import Entry, PageResult, ProviderConfiguration, Status, WatchlistError


@dataclass(frozen=True)
class FetchedPage:
    result: PageResult
    items_examined: int


class OfflinePageProvider(Protocol):
    async def page(self, entry: Entry, cursor: str | None, *, limit: int) -> FetchedPage:
        """Make at most one bounded listing attempt and report the raw entry count."""
        ...


@dataclass(frozen=True)
class ScanReport:
    watchlist_id: str
    state: str
    reason: str | None
    items: int = 0
    page_attempts: int = 0
    request_attempts: int = 0


class OneShotScanner:
    def __init__(
        self,
        unit_of_work,
        provider: OfflinePageProvider,
        *,
        configuration: ProviderConfiguration,
        page_budget: int = 2,
    ):
        if type(page_budget) is not int or not 1 <= page_budget <= 100:
            raise ValueError("invalid_page_budget")
        self._uow = unit_of_work
        self._provider = provider
        self._configuration = configuration
        self._page_budget = page_budget

    async def scan(self, *, cycle: str) -> tuple[ScanReport, ...]:
        reports = []
        after = ""
        while True:
            async with self._uow() as uow:
                entries = await uow.watchlist.list(after=after, limit=100, scanner=True)
            if not entries:
                return tuple(reports)
            for entry in entries:
                reports.append(await self._scan_channel(entry, cycle))
            after = entries[-1].id

    async def _scan_channel(self, entry: Entry, cycle: str) -> ScanReport:
        configuration = self._configuration
        fingerprint = hashlib.sha256(
            json.dumps(
                (
                    "offline-v1",
                    entry.channel_id,
                    entry.version,
                    entry.policy.page_budget,
                    entry.policy.lookback_days,
                    configuration.adapter,
                    configuration.timeout_seconds,
                    configuration.request_budget,
                    self._page_budget,
                ),
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        items = attempts = requests = 0
        try:
            async with self._uow() as uow:
                lease = await uow.discovery.claim(
                    entry.id,
                    provider=entry.provider,
                    fingerprint=fingerprint,
                    cycle=cycle,
                    expected_watchlist_version=entry.version,
                )
            if lease.state == "completed":
                return ScanReport(entry.id, "completed", "already_completed")

            coverage_through = lease.started_at
            restarted = False
            reason = "budget_exhausted"
            while (
                items < entry.policy.page_budget
                and attempts < self._page_budget
                and requests < configuration.request_budget
            ):
                limit = min(50, entry.policy.page_budget - items)
                attempts += 1
                requests += 1
                try:
                    async with asyncio.timeout(configuration.timeout_seconds):
                        fetched = await self._provider.page(entry, lease.cursor, limit=limit)
                except Exception:  # noqa: BLE001 -- isolate provider failures; cancellation propagates
                    fetched = FetchedPage(_failure(Status.TEMPORARY_FAILURE), 0)
                items += fetched.items_examined
                page = fetched.result
                if fetched.items_examined > limit:
                    page = _failure(Status.TEMPORARY_FAILURE)
                restart = page.failure == Status.CURSOR_EXPIRED
                try:
                    lease = await self._record(
                        lease, page, fetched.items_examined, coverage_through
                    )
                except WatchlistError as error:
                    if str(error) != "scan_cursor_restart_required":
                        raise
                    restart = True
                    page = _failure(Status.TEMPORARY_FAILURE)
                    lease = await self._record(
                        lease, page, fetched.items_examined, coverage_through
                    )
                if lease.state == "completed":
                    return ScanReport(entry.id, "completed", None, items, attempts, requests)
                if restart and not restarted:
                    async with self._uow() as uow:
                        lease = await uow.discovery.restart(lease)
                    restarted = True
                elif not page.checkpoint_may_advance:
                    reason = (
                        "cursor_restart_exhausted"
                        if restart
                        else (page.failure.value if page.failure else "partial_page")
                    )
                    break
        except WatchlistError as error:
            reason = str(error)
        return ScanReport(entry.id, "partial", reason, items, attempts, requests)

    async def _record(self, lease, page, items, coverage_through):
        async with self._uow() as uow:
            return await uow.discovery.record_page(
                lease,
                page,
                items_examined=items,
                requests=1,
                expires_at=datetime.now(UTC) + timedelta(days=1),
                coverage_through=coverage_through,
            )


def _failure(status: Status) -> PageResult:
    return PageResult((), "failed", failure=status)
