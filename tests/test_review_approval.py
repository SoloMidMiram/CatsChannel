"""Real dispatcher callbacks and durable review ownership without live Telegram."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from test_bot_submission_intake import RecordingSession

from cats_channel.bot.context import BotOperationRegistry, OperationLoggingMiddleware
from cats_channel.bot.routers.review import create_review_router
from cats_channel.diagnostics import configure_logging
from cats_channel.persistence import Database, SourceIdentity, TelegramMessageRef
from cats_channel.reply_chains.service import ReplyChainService
from cats_channel.review.entities import ReviewError
from cats_channel.review.service import ReviewService

CHAT = -100456
DESTINATION = -100789


@pytest.fixture
async def review_setup(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'reviews.sqlite3').as_posix()}")
    await database.create_schema_for_tests()
    async with database.unit_of_work() as uow:
        thread = await uow.threads.get_or_create(SourceIdentity("telegram", "source"))
        submission = await uow.submissions.create(
            source_provider="telegram",
            source_media_id="unique",
            source_identity_status="user_selected",
            thread_id=thread.id,
            status="validated",
            media_origin="telegram_native",
            validation_evidence={"full_decode": True},
            provenance={
                "media": {"adapter": "telegram_native"},
                "source_resolution": {
                    "status": "unresolved",
                    "method": "identity_not_verified",
                    "evidence": {},
                },
                "telegram": {"file_id": "fixture", "file_unique_id": "unique"},
            },
        )
    chains = ReplyChainService(database.unit_of_work, destination_chat_id=DESTINATION)
    await chains.create_normal_intent(submission.id, thread.id)
    transport = AsyncMock()
    transport.send_review.return_value = TelegramMessageRef(CHAT, 99)
    publisher = AsyncMock()
    publisher.approve_pilot.return_value = SimpleNamespace(
        state="confirmed", id="publication", error_category=None
    )
    service = ReviewService(
        database.unit_of_work,
        transport=transport,
        publication_service=publisher,
        review_chat_id=CHAT,
        destination_chat_id=DESTINATION,
        admin_user_id=42,
    )
    try:
        yield database, submission, transport, publisher, service
    finally:
        await database.dispose()


async def test_review_is_sent_once_and_does_not_publish(review_setup):
    _, submission, transport, publisher, service = review_setup
    first = await service.enqueue(submission.id)
    second = await service.enqueue(submission.id)
    assert first.id == second.id and second.delivery_state == "confirmed"
    transport.send_review.assert_awaited_once()
    publisher.approve_pilot.assert_not_awaited()
    button = transport.send_review.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Approve" and len(button.callback_data.encode()) <= 64


@pytest.mark.parametrize(
    "override,code",
    [
        ({"actor_id": 43}, "review_forbidden"),
        ({"chat_id": -100999}, "review_message_mismatch"),
        ({"message_id": 100}, "review_message_mismatch"),
        ({"version": 9}, "review_stale"),
    ],
)
async def test_unauthorized_forged_or_stale_click_never_publishes(review_setup, override, code):
    _, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    arguments = {"version": item.version, "actor_id": 42, "chat_id": CHAT, "message_id": 99}
    arguments.update(override)
    with pytest.raises(ReviewError) as error:
        await service.approve(item.id, **arguments)
    assert error.value.code == code
    publisher.approve_pilot.assert_not_awaited()


async def test_duplicate_approval_is_audited_once(review_setup):
    _, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    result = await service.approve(item.id, item.version, actor_id=42, chat_id=CHAT, message_id=99)
    duplicate = await service.approve(
        item.id, item.version, actor_id=42, chat_id=CHAT, message_id=99
    )
    assert result.decision_state == duplicate.decision_state == "approved"
    assert result.reviewer_id == 42 and result.reviewed_at is not None
    assert result.version == item.version + 1
    publisher.approve_pilot.assert_awaited_once_with(submission.id)


async def test_concurrent_click_does_not_take_existing_approval(review_setup):
    _, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    entered, release = asyncio.Event(), asyncio.Event()

    async def publish(*args):
        entered.set()
        await release.wait()
        return SimpleNamespace(state="confirmed", id="publication", error_category=None)

    publisher.approve_pilot.side_effect = publish
    task = asyncio.create_task(
        service.approve(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        other = await service.approve(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
        assert other.decision_state == "approving"
        release.set()
        assert (await task).decision_state == "approved"
        publisher.approve_pilot.assert_awaited_once()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_ambiguous_review_send_is_not_resent_on_restart(review_setup):
    _, submission, transport, publisher, service = review_setup
    transport.send_review.side_effect = TimeoutError("token=PRIVATE")
    item = await service.enqueue(submission.id)
    assert item.delivery_state == "unknown"
    await service.recover_abandoned()
    assert (await service.enqueue(submission.id)).delivery_state == "unknown"
    transport.send_review.assert_awaited_once()
    publisher.approve_pilot.assert_not_awaited()


async def test_cancelled_approval_retains_audit_without_retry(review_setup):
    _, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    publisher.approve_pilot.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.approve(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    result = await service.get(item.id)
    assert result.decision_state == "needs_reconciliation" and result.reviewer_id == 42
    await service.approve(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    publisher.approve_pilot.assert_awaited_once()


async def test_changed_publication_destination_fails_closed(review_setup):
    _, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    service.destination = -100999
    with pytest.raises(ReviewError):
        await service.approve(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    publisher.approve_pilot.assert_not_awaited()


async def test_real_dispatcher_accepts_admin_channel_callback_only(review_setup):
    _, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    session = RecordingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    logger = configure_logging("WARNING")
    dispatcher = Dispatcher(logger=logger)
    router = create_review_router(service)
    router.callback_query.outer_middleware(
        OperationLoggingMiddleware(logger, registry=BotOperationRegistry())
    )
    dispatcher.include_router(router)

    def update(actor, number):
        return Update(
            update_id=number,
            callback_query=CallbackQuery(
                id=str(number),
                from_user=User(id=actor, is_bot=False, first_name="Fixture"),
                chat_instance="fixture",
                data=f"reviewapprove:{item.id}:1",
                message=Message(
                    message_id=99, date=datetime.now(UTC), chat=Chat(id=CHAT, type="channel")
                ),
            ),
        )

    try:
        await dispatcher.feed_update(bot, update(43, 1))
        publisher.approve_pilot.assert_not_awaited()
        await dispatcher.feed_update(bot, update(42, 2))
        await dispatcher.feed_update(bot, update(42, 3))
        publisher.approve_pilot.assert_awaited_once()
        assert (await service.get(item.id)).decision_state == "approved"
    finally:
        await bot.session.close()


async def test_application_routes_channel_approval_outside_private_intake(review_setup):
    from cats_channel.bot.application import create_bot_application
    from cats_channel.config import Settings

    database, submission, transport, publisher, _ = review_setup
    bot = Bot("123456:TEST_TOKEN", session=RecordingSession())
    settings = Settings(
        _env_file=None,
        bot_token="123456:TEST_TOKEN",
        admin_user_id=42,
        channel_id=str(DESTINATION),
        review_channel_id=CHAT,
    )
    app = create_bot_application(settings, bot=bot, persistence_unit_of_work=database.unit_of_work)
    service = app.dispatcher.workflow_data["review_service"]
    service.transport = transport
    service.publisher = publisher
    item = await service.enqueue(submission.id)
    update = Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="channel-callback",
            from_user=User(id=42, is_bot=False, first_name="Fixture"),
            chat_instance="fixture",
            data=f"reviewapprove:{item.id}:1",
            message=Message(
                message_id=99, date=datetime.now(UTC), chat=Chat(id=CHAT, type="channel")
            ),
        ),
    )
    try:
        await app.dispatcher.feed_update(bot, update)
        publisher.approve_pilot.assert_awaited_once_with(submission.id)
        assert (await service.get(item.id)).decision_state == "approved"
    finally:
        await bot.session.close()


async def test_approval_uses_real_publication_exact_parent_and_keeps_normal_tail(review_setup):
    from test_publication import Transport

    from cats_channel.publication.service import PublicationService

    database, root_submission, transport, _, service = review_setup
    delivery = Transport()
    # The fake publication transport uses the existing publication suite's destination.
    from test_publication import DESTINATION as PUBLISH_DESTINATION

    chains = ReplyChainService(database.unit_of_work, destination_chat_id=PUBLISH_DESTINATION)
    publisher = PublicationService(
        database.unit_of_work,
        reply_chains=chains,
        transport=delivery,
        destination_chat_id=PUBLISH_DESTINATION,
    )
    root = await publisher.approve_pilot(root_submission.id)
    async with database.unit_of_work() as uow:
        source = await uow.submissions.get(root_submission.id)
        reply = await uow.submissions.create(
            source_provider="telegram",
            source_media_id="reply-unique",
            source_identity_status="unresolved",
            status="validated",
            thread_id=source.thread_id,
        )
    await chains.create_interactive_intent(reply.id, source.thread_id, root.post_id)
    service.publisher = publisher
    service.destination = PUBLISH_DESTINATION
    item = await service.enqueue(reply.id)
    assert len(delivery.sends) == 1
    approved = await service.approve(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    assert approved.decision_state == "approved" and len(delivery.sends) == 2
    assert delivery.sends[-1][1] == TelegramMessageRef(PUBLISH_DESTINATION, 1)
    async with database.unit_of_work() as uow:
        thread = await uow.threads.get(source.thread_id)
        assert thread.tail_post_id == root.post_id
    transport.send_review.assert_awaited_once()
