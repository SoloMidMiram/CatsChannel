import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Video
from test_bot_submission_intake import application, message_update

from cats_channel.bot.entry import ReplyTarget
from cats_channel.reply_tokens import new_reply_token


async def test_video_during_reply_resolution_is_processed_once():
    entered, release = asyncio.Event(), asyncio.Event()
    target = ReplyTarget(str(uuid4()), str(uuid4()))
    resolver = AsyncMock()

    async def resolve(*args, **kwargs):
        entered.set()
        await release.wait()
        return target

    resolver.resolve.side_effect = resolve
    app, bot, _session, intake, *_ = application(resolver=resolver)
    entry = asyncio.create_task(
        app.dispatcher.feed_update(bot, message_update(text=f"/start catreply_{new_reply_token()}"))
    )
    video = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        # Start the original update once; completion is not required until resolution.
        video = asyncio.create_task(
            app.dispatcher.feed_update(
                bot,
                message_update(
                    update_id=2,
                    video=Video(
                        file_id="fixture", file_unique_id="unique", width=10, height=10, duration=1
                    ),
                ),
            )
        )
        # An explicit scheduling barrier, not an elapsed-time sleep.
        scheduled = asyncio.Event()
        asyncio.get_running_loop().call_soon(scheduled.set)
        await scheduled.wait()
        intake.process.assert_not_awaited()
        release.set()
        await asyncio.wait_for(asyncio.gather(entry, video), 3)
        intake.process.assert_awaited_once()
        placement = intake.process.await_args.kwargs["placement"]
        assert placement.selected_parent_post_id == target.post_id
        assert placement.thread_id == target.thread_id
    finally:
        release.set()
        for task in (entry, video):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*[t for t in (entry, video) if t is not None], return_exceptions=True)
        await bot.session.close()


@pytest.mark.parametrize("action", ["cancel", "replace", "reject", "failure", "timeout"])
async def test_pending_video_never_adopts_invalid_or_replaced_entry(action):
    entered, release = asyncio.Event(), asyncio.Event()
    target = ReplyTarget(str(uuid4()), str(uuid4()))
    resolver = AsyncMock()

    async def resolve(*args, **kwargs):
        entered.set()
        await release.wait()
        if action == "failure":
            raise ValueError("private fixture")
        if action == "timeout":
            raise TimeoutError()
        return None if action == "reject" else target

    resolver.resolve.side_effect = resolve
    app, bot, session, intake, *_ = application(resolver=resolver)
    entry = asyncio.create_task(
        app.dispatcher.feed_update(bot, message_update(text=f"/start catreply_{new_reply_token()}"))
    )
    await asyncio.wait_for(entered.wait(), 2)
    video = asyncio.create_task(
        app.dispatcher.feed_update(
            bot,
            message_update(
                update_id=2,
                video=Video(
                    file_id="fixture", file_unique_id="unique", width=10, height=10, duration=1
                ),
            ),
        )
    )
    scheduled = asyncio.Event()
    asyncio.get_running_loop().call_soon(scheduled.set)
    await scheduled.wait()
    try:
        if action in ("cancel", "replace"):
            await app.dispatcher.feed_update(
                bot, message_update(update_id=3, text="/cancel" if action == "cancel" else "/post")
            )
        release.set()
        await asyncio.wait_for(asyncio.gather(entry, video), 3)
        intake.process.assert_not_awaited()
        assert any("Video not accepted" in (getattr(m, "text", "") or "") for m in session.methods)
    finally:
        release.set()
        for task in (entry, video):
            if not task.done():
                task.cancel()
        await asyncio.gather(entry, video, return_exceptions=True)
        await bot.session.close()


async def test_concurrent_duplicate_video_is_admitted_once():
    entered, release = asyncio.Event(), asyncio.Event()
    resolver = AsyncMock()
    target = ReplyTarget(str(uuid4()), str(uuid4()))

    async def resolve(*args, **kwargs):
        entered.set()
        await release.wait()
        return target

    resolver.resolve.side_effect = resolve
    app, bot, _, intake, *_ = application(resolver=resolver)
    entry = asyncio.create_task(
        app.dispatcher.feed_update(bot, message_update(text=f"/start catreply_{new_reply_token()}"))
    )
    await asyncio.wait_for(entered.wait(), 2)
    update = message_update(
        update_id=2,
        video=Video(file_id="fixture", file_unique_id="unique", width=10, height=10, duration=1),
    )
    first = asyncio.create_task(app.dispatcher.feed_update(bot, update))
    second = asyncio.create_task(app.dispatcher.feed_update(bot, update))
    scheduled = asyncio.Event()
    asyncio.get_running_loop().call_soon(scheduled.set)
    await scheduled.wait()
    release.set()
    try:
        await asyncio.wait_for(asyncio.gather(entry, first, second), 3)
        intake.process.assert_awaited_once()
        await app.dispatcher.feed_update(bot, update)
        intake.process.assert_awaited_once()
    finally:
        release.set()
        for task in (entry, first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(entry, first, second, return_exceptions=True)
        await bot.session.close()


async def test_resolver_deadline_expires_without_intake(monkeypatch):
    from cats_channel.bot.routers import post

    monkeypatch.setattr(post, "ENTRY_RESOLUTION_SECONDS", 0)
    resolver = AsyncMock()
    blocked = asyncio.Event()
    resolver.resolve.side_effect = lambda *a, **kw: None

    async def resolve(*args, **kwargs):
        await blocked.wait()

    resolver.resolve.side_effect = resolve
    app, bot, session, intake, *_ = application(resolver=resolver)
    try:
        await asyncio.wait_for(
            app.dispatcher.feed_update(
                bot, message_update(text=f"/start catreply_{new_reply_token()}")
            ),
            2,
        )
        intake.process.assert_not_awaited()
        state = app.dispatcher.fsm.get_context(bot=bot, chat_id=42, user_id=42)
        assert await state.get_state() is None
        assert session.methods
        assert app.flow_coordinator.pending_count == 0
    finally:
        await bot.session.close()


async def test_independent_actor_cannot_use_pending_admin_entry():
    entered, release = asyncio.Event(), asyncio.Event()
    resolver = AsyncMock()

    async def resolve(*args, **kwargs):
        entered.set()
        await release.wait()
        return ReplyTarget(str(uuid4()), str(uuid4()))

    resolver.resolve.side_effect = resolve
    app, bot, _, intake, *_ = application(resolver=resolver)
    entry = asyncio.create_task(
        app.dispatcher.feed_update(bot, message_update(text=f"/start catreply_{new_reply_token()}"))
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await app.dispatcher.feed_update(
            bot,
            message_update(
                update_id=2,
                user_id=99,
                video=Video(
                    file_id="fixture", file_unique_id="unique", width=10, height=10, duration=1
                ),
            ),
        )
        intake.process.assert_not_awaited()
        release.set()
        await asyncio.wait_for(entry, 2)
        intake.process.assert_not_awaited()
    finally:
        release.set()
        if not entry.done():
            entry.cancel()
        await asyncio.gather(entry, return_exceptions=True)
        await bot.session.close()


async def test_new_reply_replaces_pending_entry_without_parent_substitution():
    entered, release = asyncio.Event(), asyncio.Event()
    old = ReplyTarget(str(uuid4()), str(uuid4()))
    new = ReplyTarget(str(uuid4()), str(uuid4()))
    resolver = AsyncMock()
    count = 0

    async def resolve(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            await release.wait()
            return old
        return new

    resolver.resolve.side_effect = resolve
    app, bot, _, intake, *_ = application(resolver=resolver)
    entry = asyncio.create_task(
        app.dispatcher.feed_update(bot, message_update(text=f"/start catreply_{new_reply_token()}"))
    )
    await asyncio.wait_for(entered.wait(), 2)
    video = asyncio.create_task(
        app.dispatcher.feed_update(
            bot,
            message_update(
                update_id=2,
                video=Video(
                    file_id="fixture", file_unique_id="unique", width=10, height=10, duration=1
                ),
            ),
        )
    )
    scheduled = asyncio.Event()
    asyncio.get_running_loop().call_soon(scheduled.set)
    await scheduled.wait()
    try:
        await app.dispatcher.feed_update(
            bot, message_update(update_id=3, text=f"/start catreply_{new_reply_token()}")
        )
        release.set()
        await asyncio.wait_for(asyncio.gather(entry, video), 3)
        intake.process.assert_not_awaited()
        state = app.dispatcher.fsm.get_context(bot=bot, chat_id=42, user_id=42)
        assert (await state.get_data())["parent_post_id"] == new.post_id
    finally:
        release.set()
        for task in (entry, video):
            if not task.done():
                task.cancel()
        await asyncio.gather(entry, video, return_exceptions=True)
        await bot.session.close()
