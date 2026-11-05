"""Authorized local application API; provider awaits never hold a DB transaction."""

import asyncio
from datetime import UTC, datetime

from .domain import Resolution, ScanPolicy, Status, WatchlistError, normalize


class WatchlistService:
    def __init__(self, unit_of_work, *, authorization, resolver=None, capacity=100):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("invalid_capacity")
        self.uow = unit_of_work
        self.authorization = authorization
        self.resolver = resolver
        self.capacity = capacity

    def authorize(self, operator, operation):
        if operator is None or not self.authorization.allows(operator, operation):
            raise WatchlistError("unauthorized")

    async def resolve(self, reference):
        if self.resolver is None:
            return Resolution(Status.UNRESOLVED, evidence="resolver_not_configured")
        try:
            async with asyncio.timeout(30):
                result = await self.resolver.resolve(reference)
            if not isinstance(result, Resolution):
                raise TypeError("invalid_provider_result")
            if (
                reference.startswith("UC")
                and result.status == Status.RESOLVED
                and reference != result.channel_id
            ):
                return Resolution(Status.AMBIGUOUS)
            return result
        except Exception:  # noqa: BLE001 -- sanitize untrusted provider failures
            # Cancellation propagates; provider exception payloads never enter logs/storage.
            return Resolution(Status.TEMPORARY_FAILURE)

    async def register(self, reference, *, operator=None):
        self.authorize(operator, "register")
        reference = normalize(reference)
        async with self.uow() as uow:
            before = await uow.watchlist.find(reference)
        started_at = datetime.now(UTC)
        result = await self.resolve(reference)
        async with self.uow() as uow:
            repo = uow.watchlist
            await repo.lock()
            return await repo.apply_resolution(
                reference, before, result, operator, self.capacity, started_at
            )

    async def refresh_resolution(self, entry_id, *, operator=None):
        self.authorize(operator, "refresh_resolution")
        before = await self.inspect(entry_id)
        if before.retired:
            raise WatchlistError("retired")
        if before.channel_id is None:
            started_at = datetime.now(UTC)
            result = await self.resolve(before.reference)
            async with self.uow() as uow:
                await uow.watchlist.lock()
                registration = await uow.watchlist.apply_resolution(
                    before.reference, before, result, operator, self.capacity, started_at
                )
                return registration.entry
        result = await self.resolve(before.channel_id)
        async with self.uow() as uow:
            repo = uow.watchlist
            await repo.lock()
            return await repo.refresh(before, result, operator)

    async def list(self, *, after="", limit=100, scanner=False):
        async with self.uow() as uow:
            return await uow.watchlist.list(after=after, limit=limit, scanner=scanner)

    async def inspect(self, entry_id):
        async with self.uow() as uow:
            entry = await uow.watchlist.get(entry_id)
            if entry is None:
                raise WatchlistError("not_found")
            return entry

    async def history(self, entry_id, *, limit=100):
        async with self.uow() as uow:
            return await uow.watchlist.history(entry_id, limit=limit)

    async def change(self, entry_id, operator, operation, *, enabled=None, policy=None):
        self.authorize(operator, operation)
        async with self.uow() as uow:
            repo = uow.watchlist
            await repo.lock()
            return await repo.change(entry_id, operator, operation, enabled, policy)

    async def set_enabled(self, entry_id, enabled, *, operator=None):
        if type(enabled) is not bool:
            raise ValueError("invalid_enabled")
        return await self.change(entry_id, operator, "set_enabled", enabled=enabled)

    async def set_scan_policy(self, entry_id, policy, *, operator=None):
        if not isinstance(policy, ScanPolicy):
            raise TypeError("invalid_scan_policy")
        return await self.change(entry_id, operator, "set_scan_policy", policy=policy)

    async def retire(self, entry_id, *, operator=None):
        return await self.change(entry_id, operator, "retire")
