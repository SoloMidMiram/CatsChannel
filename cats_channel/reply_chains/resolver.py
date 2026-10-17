"""Database-backed reply entry with explicit actor authorization and safe denial."""

from collections.abc import Awaitable, Callable

from ..reply_tokens import ReplyTarget
from .service import ReplyChainService, token_digest

ActorAuthorizer = Callable[[int, ReplyTarget], Awaitable[bool]]


class DatabaseReplyTargetResolver:
    def __init__(self, service: ReplyChainService, *, authorize_actor: ActorAuthorizer) -> None:
        self._service = service
        self._authorize_actor = authorize_actor

    async def resolve(self, token: str, *, actor_id: int) -> ReplyTarget | None:
        try:
            digest = token_digest(token)
            if type(actor_id) is not int or actor_id <= 0:
                return None
            async with self._service.unit_of_work() as uow:
                entry = await uow.reply_tokens.get(digest)
                now = self._service.now()
                if (
                    entry is None
                    or entry.revoked_at is not None
                    or (entry.expires_at is not None and entry.expires_at <= now)
                    or entry.created_at > now
                ):
                    return None
                post = await uow.threads.get_post(entry.post_id)
                if post is None:
                    return None
                thread = await self._service._thread(uow, post.thread_id)
                if thread.root_post_id is None:
                    return None
                await self._service._ancestry(uow, thread, post.id)
                target = ReplyTarget(post.id, thread.id)
                if not await self._authorize_actor(actor_id, target):
                    return None
                await self._service._projection(uow, post.id)
                return target
        except Exception:  # noqa: BLE001 - all unavailable entries have the same safe result
            return None
