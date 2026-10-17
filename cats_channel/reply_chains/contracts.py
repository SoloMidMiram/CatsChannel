"""Persistence contracts for immutable intents and reusable reply entries."""

from datetime import datetime
from typing import Protocol

from .entities import PlacementMode, PostIntent, ReplyEntryToken


class IntentRepository(Protocol):
    async def create(
        self,
        *,
        submission_id: str,
        thread_id: str,
        mode: PlacementMode,
        selected_parent_post_id: str | None,
    ) -> PostIntent: ...

    async def get(self, intent_id: str) -> PostIntent | None: ...


class ReplyTokenRepository(Protocol):
    async def create(
        self,
        *,
        token_digest: str,
        post_id: str,
        created_at: datetime,
        expires_at: datetime | None,
    ) -> ReplyEntryToken: ...

    async def get(self, token_digest: str) -> ReplyEntryToken | None: ...

    async def revoke(self, token_digest: str, *, revoked_at: datetime) -> bool: ...
