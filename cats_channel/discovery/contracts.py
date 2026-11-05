"""Replaceable resolution and trusted-local authorization."""

from datetime import datetime
from typing import Protocol

from .domain import Change, Entry, Operator, Registration, Resolution, ScanPolicy


class ChannelResolver(Protocol):
    async def resolve(self, reference: str) -> Resolution: ...


class OperatorAuthorization(Protocol):
    def allows(self, operator: Operator, operation: str) -> bool: ...


class WatchlistRepository(Protocol):
    async def lock(self) -> None: ...
    async def get(self, entry_id: str) -> Entry | None: ...
    async def find(self, reference: str) -> Entry | None: ...
    async def history(self, entry_id: str, *, limit: int = 100) -> tuple[Change, ...]: ...
    async def list(
        self, *, after: str = "", limit: int = 100, scanner: bool = False
    ) -> tuple[Entry, ...]: ...
    async def apply_resolution(
        self,
        reference: str,
        before: Entry | None,
        result: Resolution,
        operator: Operator,
        capacity: int,
        started_at: datetime,
    ) -> Registration: ...
    async def refresh(self, before: Entry, result: Resolution, operator: Operator) -> Entry: ...
    async def change(
        self,
        entry_id: str,
        operator: Operator,
        operation: str,
        enabled: bool | None,
        policy: ScanPolicy | None,
    ) -> Entry: ...
