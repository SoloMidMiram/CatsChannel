"""Real dispatcher callbacks and durable review ownership without live Telegram."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from test_bot_submission_intake import RecordingSession
from test_reply_chains import chain_database as _chain_database

from cats_channel.bot.context import BotOperationRegistry, OperationLoggingMiddleware
from cats_channel.bot.routers.review import create_review_router
from cats_channel.diagnostics import configure_logging
from cats_channel.persistence import SourceIdentity, TelegramMessageRef
from cats_channel.reply_chains.service import ReplyChainService
from cats_channel.review.entities import ReviewError
from cats_channel.review.service import ReviewService

CHAT = -100456
DESTINATION = -100789
chain_database = _chain_database


@pytest.fixture
async def review_setup(chain_database):
    database = chain_database
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
    yield database, submission, transport, publisher, service


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


@pytest.mark.parametrize("phase", ["delivery", "approval"])
async def test_postgres_review_competing_claims_have_one_owner(review_setup, phase):
    database, submission, transport, publisher, service = review_setup
    if database.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL simultaneous writer contract")
    if phase == "approval":
        item = await service.enqueue(submission.id)
    else:
        async with database.unit_of_work() as uow:
            item = await uow.reviews.create(submission.id, CHAT, DESTINATION)
    ready = asyncio.Event()
    waiting = 0

    async def claim(actor):
        nonlocal waiting
        async with database.unit_of_work() as uow:
            snapshot = await uow.reviews.get(item.id)
            waiting += 1
            if waiting == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 5)
            if phase == "delivery":
                return await uow.reviews.claim_delivery(snapshot)
            return await uow.reviews.claim_approval(snapshot, actor, datetime.now(UTC))

    results = await asyncio.wait_for(asyncio.gather(claim(42), claim(43)), 10)
    assert sorted(results) == [False, True]
    stored = await service.get(item.id)
    if phase == "approval":
        assert stored.decision_state == "approving"
        assert stored.reviewer_id == (42 if results[0] else 43)
        assert stored.reviewed_at is not None
    else:
        assert stored.delivery_state == "sending"
    await service.recover_abandoned()
    recovered = await service.enqueue(submission.id)
    if phase == "approval":
        assert recovered.decision_state == "needs_reconciliation"
        assert recovered.reviewer_id == stored.reviewer_id
        transport.send_review.assert_awaited_once()
    else:
        assert recovered.delivery_state == "unknown"
        transport.send_review.assert_not_awaited()
    publisher.approve_pilot.assert_not_awaited()


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


async def assert_rejected_without_effects(database, submission, service, item_id):
    from sqlalchemy import func, select

    from cats_channel.persistence.models import CatPostModel, PublicationModel

    item = await service.get(item_id)
    assert item.decision_state == "rejected" and item.decision_action == "reject"
    assert item.reviewer_id == 42 and item.reviewed_at is not None
    assert item.rejection_reason == "unsuitable" and item.publication_id is None
    async with database.unit_of_work() as uow:
        assert (await uow.submissions.get(submission.id)).status == "rejected"
        assert await uow.threads.get_post_for_submission(submission.id) is None
    async with database.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(CatPostModel)) == 0
        assert await connection.scalar(select(func.count()).select_from(PublicationModel)) == 0
    return item


async def test_reject_is_terminal_audited_and_restart_never_publishes(review_setup):
    database, submission, transport, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    result = await service.reject(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    assert result.version == 2
    for decide in (service.reject, service.approve):
        assert (
            await decide(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
        ).decision_state == "rejected"
    await database.engine.dispose()
    restarted = ReviewService(
        database.unit_of_work,
        transport=transport,
        publication_service=publisher,
        review_chat_id=CHAT,
        destination_chat_id=DESTINATION,
        admin_user_id=42,
    )
    await restarted.recover_abandoned()
    stored = await assert_rejected_without_effects(database, submission, restarted, item.id)
    assert stored.reviewed_at == result.reviewed_at
    publisher.approve_pilot.assert_not_awaited()
    transport.send_review.assert_awaited_once()


async def test_rejected_submission_cannot_use_direct_pilot_publisher(review_setup):
    from cats_channel.publication.errors import PublicationError
    from cats_channel.publication.service import PublicationService

    database, submission, _, _, service = review_setup
    item = await service.enqueue(submission.id)
    await service.reject(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    transport = AsyncMock()
    publisher = PublicationService(
        database.unit_of_work,
        reply_chains=ReplyChainService(database.unit_of_work, destination_chat_id=DESTINATION),
        transport=transport,
        destination_chat_id=DESTINATION,
    )
    with pytest.raises(PublicationError):
        await publisher.approve_pilot(submission.id)
    transport.send.assert_not_awaited()
    await assert_rejected_without_effects(database, submission, service, item.id)


@pytest.mark.parametrize(
    "override,code",
    [
        ({"actor_id": 43}, "review_forbidden"),
        ({"chat_id": -100999}, "review_message_mismatch"),
        ({"message_id": 100}, "review_message_mismatch"),
        ({"version": 2}, "review_stale"),
        ({"reason": "private caption or arbitrary text"}, "review_reason_invalid"),
    ],
)
async def test_reject_denies_forged_stale_unauthorized_and_unsafe_reason(
    review_setup, override, code
):
    _, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    args = {"version": 1, "actor_id": 42, "chat_id": CHAT, "message_id": 99}
    args.update(override)
    with pytest.raises(ReviewError) as error:
        await service.reject(item.id, **args)
    assert error.value.code == code
    assert (await service.get(item.id)).decision_state == "pending"
    publisher.approve_pilot.assert_not_awaited()


async def test_rejection_transaction_rolls_back_decision_and_submission_together(review_setup):
    database, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)
    with pytest.raises(RuntimeError, match="rollback"):
        async with database.unit_of_work() as uow:
            assert await uow.reviews.reject(item, 42, datetime.now(UTC), "unsuitable")
            raise RuntimeError("rollback")
    assert (await service.get(item.id)).decision_state == "pending"
    async with database.unit_of_work() as uow:
        assert (await uow.submissions.get(submission.id)).status == "validated"
    await service.reject(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    await assert_rejected_without_effects(database, submission, service, item.id)
    publisher.approve_pilot.assert_not_awaited()


async def test_approval_claim_excludes_rejection_before_publication_finishes(review_setup):
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
        await asyncio.wait_for(entered.wait(), 3)
        result = await service.reject(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
        assert result.decision_state == "approving" and result.rejection_reason is None
    finally:
        release.set()
        await task
    publisher.approve_pilot.assert_awaited_once()


async def test_postgres_approve_and_reject_transactions_share_one_owner(review_setup):
    database, submission, _, _, service = review_setup
    if database.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL simultaneous writer contract")
    item = await service.enqueue(submission.id)
    barrier = asyncio.Event()
    waiting = 0

    async def claim(rejecting):
        nonlocal waiting
        async with database.unit_of_work() as uow:
            snapshot = await uow.reviews.get(item.id)
            waiting += 1
            if waiting == 2:
                barrier.set()
            await asyncio.wait_for(barrier.wait(), 5)
            if rejecting:
                return await uow.reviews.reject(snapshot, 42, datetime.now(UTC), "unsuitable")
            return await uow.reviews.claim_approval(snapshot, 42, datetime.now(UTC))

    results = await asyncio.wait_for(asyncio.gather(claim(False), claim(True)), 10)
    assert sorted(results) == [False, True]
    stored = await service.get(item.id)
    assert stored.decision_action == ("approve" if results[0] else "reject")
    async with database.unit_of_work() as uow:
        status = (await uow.submissions.get(submission.id)).status
        assert status == ("validated" if results[0] else "rejected")


async def test_failed_submitter_notification_cannot_undo_or_replay_rejection(review_setup):
    database, submission, _, publisher, service = review_setup
    async with database.unit_of_work() as uow:
        handoff = await uow.handoffs.create(
            token_digest="a" * 64,
            actor_id=42,
            conversation_chat_id=42,
            operation="post",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert await uow.handoffs.consume(
            handoff_id=handoff.id, submission_id=submission.id, consumed_at=datetime.now(UTC)
        )
    notifier = AsyncMock(side_effect=RuntimeError("private token"))
    service.rejection_notifier = notifier
    item = await service.enqueue(submission.id)
    await service.reject(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    await service.reject(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
    notifier.assert_awaited_once_with(42, "Your submission was rejected.")
    await assert_rejected_without_effects(database, submission, service, item.id)
    publisher.approve_pilot.assert_not_awaited()


@pytest.mark.parametrize("fail", [False, True])
async def test_dispatcher_rejection_controls_and_failed_notifications(review_setup, fail):
    from aiogram.methods import AnswerCallbackQuery, EditMessageCaption, SendVideo

    database, submission, _, publisher, service = review_setup
    item = await service.enqueue(submission.id)

    class Session(RecordingSession):
        async def make_request(self, bot, method, timeout=None):
            if fail and isinstance(method, (EditMessageCaption, AnswerCallbackQuery)):
                self.methods.append(method)
                raise RuntimeError("private api token")
            return await super().make_request(bot, method, timeout)

    session = Session()
    bot = Bot("123456:TEST_TOKEN", session=session)
    logger = configure_logging("WARNING")
    dispatcher = Dispatcher(logger=logger)
    router = create_review_router(service)
    router.callback_query.outer_middleware(
        OperationLoggingMiddleware(logger, registry=BotOperationRegistry())
    )
    dispatcher.include_router(router)
    try:
        for number in (1, 2):
            update = Update(
                update_id=number,
                callback_query=CallbackQuery(
                    id=str(number),
                    from_user=User(id=42, is_bot=False, first_name="Fixture"),
                    chat_instance="fixture",
                    data=f"reviewreject:{item.id}:1",
                    message=Message(
                        message_id=99, date=datetime.now(UTC), chat=Chat(id=CHAT, type="channel")
                    ),
                ),
            )
            await dispatcher.feed_update(bot, update)
        await assert_rejected_without_effects(database, submission, service, item.id)
        edits = [m for m in session.methods if isinstance(m, EditMessageCaption)]
        assert edits and all(m.reply_markup is None and "Rejected" in m.caption for m in edits)
        assert not any(isinstance(m, SendVideo) for m in session.methods)
        publisher.approve_pilot.assert_not_awaited()
    finally:
        await bot.session.close()


async def test_competing_dispatcher_approve_reject_has_one_terminal_owner(review_setup):
    from test_publication import Transport

    from cats_channel.publication.service import PublicationService

    database, submission, _, _, service = review_setup
    delivery = Transport()
    service.publisher = PublicationService(
        database.unit_of_work,
        reply_chains=ReplyChainService(database.unit_of_work, destination_chat_id=DESTINATION),
        transport=delivery,
        destination_chat_id=DESTINATION,
    )

    # Transport's fixed destination is irrelevant to rejection; use a destination-
    # matching returned reference if approval wins the transaction race.
    async def send(media, *, parent):
        delivery.sends.append((media.id, parent))
        return TelegramMessageRef(DESTINATION, 1)

    delivery.send = send
    item = await service.enqueue(submission.id)
    bot = Bot("123456:TEST_TOKEN", session=RecordingSession())
    logger = configure_logging("WARNING")
    dispatcher = Dispatcher(logger=logger)
    router = create_review_router(service)
    router.callback_query.outer_middleware(
        OperationLoggingMiddleware(logger, registry=BotOperationRegistry())
    )
    dispatcher.include_router(router)

    def update(action, number):
        return Update(
            update_id=number,
            callback_query=CallbackQuery(
                id=str(number),
                from_user=User(id=42, is_bot=False, first_name="Fixture"),
                chat_instance="fixture",
                data=f"review{action}:{item.id}:1",
                message=Message(
                    message_id=99, date=datetime.now(UTC), chat=Chat(id=CHAT, type="channel")
                ),
            ),
        )

    try:
        await asyncio.wait_for(
            asyncio.gather(
                dispatcher.feed_update(bot, update("approve", 1)),
                dispatcher.feed_update(bot, update("reject", 2)),
            ),
            10,
        )
        stored = await service.get(item.id)
        assert stored.decision_state in {"approved", "rejected"}
        assert stored.decision_action == (
            "approve" if stored.decision_state == "approved" else "reject"
        )
        assert len(delivery.sends) == (1 if stored.decision_state == "approved" else 0)
        async with database.unit_of_work() as uow:
            post = await uow.threads.get_post_for_submission(submission.id)
            assert (post is not None) == (stored.decision_state == "approved")
        if stored.decision_state == "rejected":
            await assert_rejected_without_effects(database, submission, service, item.id)
    finally:
        await bot.session.close()


async def test_rejection_serializes_with_direct_pilot_placement(review_setup, monkeypatch):
    from cats_channel.persistence.repositories import SqlAlchemyThreadRepository
    from cats_channel.publication.errors import PublicationError
    from cats_channel.publication.service import PublicationService

    database, submission, _, _, service = review_setup
    if database.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrent placement contract")
    item = await service.enqueue(submission.id)
    checked, release = asyncio.Event(), asyncio.Event()
    original = SqlAlchemyThreadRepository.get_post_for_submission

    async def pause_after_check(repository, submission_id):
        post = await original(repository, submission_id)
        if asyncio.current_task().get_name() == "reject-before-placement":
            checked.set()
            await asyncio.wait_for(release.wait(), 10)
        return post

    monkeypatch.setattr(SqlAlchemyThreadRepository, "get_post_for_submission", pause_after_check)
    transport = AsyncMock()
    transport.send.return_value = TelegramMessageRef(DESTINATION, 101)
    publisher = PublicationService(
        database.unit_of_work,
        reply_chains=ReplyChainService(database.unit_of_work, destination_chat_id=DESTINATION),
        transport=transport,
        destination_chat_id=DESTINATION,
    )
    rejection = asyncio.create_task(
        service.reject(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99),
        name="reject-before-placement",
    )
    publication = None
    try:
        await asyncio.wait_for(checked.wait(), 5)
        publication = asyncio.create_task(publisher.approve_pilot(submission.id))
        await asyncio.wait({publication}, timeout=0.5)
    finally:
        release.set()
        await rejection
        if publication is not None:
            result = (await asyncio.gather(publication, return_exceptions=True))[0]
    assert isinstance(result, PublicationError)
    transport.send.assert_not_awaited()
    await assert_rejected_without_effects(database, submission, service, item.id)


async def test_direct_pilot_placement_excludes_concurrent_rejection(review_setup, monkeypatch):
    from cats_channel.publication.service import PublicationService

    database, submission, _, _, service = review_setup
    if database.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrent placement contract")
    item = await service.enqueue(submission.id)
    checked, release = asyncio.Event(), asyncio.Event()
    chains = ReplyChainService(database.unit_of_work, destination_chat_id=DESTINATION)
    original = chains._submission

    async def pause_before_placement(*args, **kwargs):
        await original(*args, **kwargs)
        checked.set()
        await asyncio.wait_for(release.wait(), 10)

    monkeypatch.setattr(chains, "_submission", pause_before_placement)
    transport = AsyncMock()
    transport.send.return_value = TelegramMessageRef(DESTINATION, 101)
    publisher = PublicationService(
        database.unit_of_work,
        reply_chains=chains,
        transport=transport,
        destination_chat_id=DESTINATION,
    )
    publication = asyncio.create_task(publisher.approve_pilot(submission.id))
    rejection = None
    try:
        await asyncio.wait_for(checked.wait(), 5)
        rejection = asyncio.create_task(
            service.reject(item.id, 1, actor_id=42, chat_id=CHAT, message_id=99)
        )
        await asyncio.wait({rejection}, timeout=0.5)
    finally:
        release.set()
        published = await publication
        if rejection is not None:
            result = (await asyncio.gather(rejection, return_exceptions=True))[0]
    assert published.state == "confirmed"
    assert isinstance(result, ReviewError) and result.code == "review_already_placed"
    transport.send.assert_awaited_once()
    assert (await service.get(item.id)).decision_state == "pending"
    async with database.unit_of_work() as uow:
        assert (await uow.submissions.get(submission.id)).status == "validated"
        assert await uow.threads.get_post_for_submission(submission.id) is not None


@pytest.mark.parametrize("private_review", [True, False])
async def test_isolation_gate_and_rejection_through_composed_application(
    review_setup, private_review
):
    from aiogram.methods import SendVideo
    from test_review_isolation import configured, readable_bot

    from cats_channel.bot import create_bot_application
    from cats_channel.errors import MediaError

    database, submission, _, _, service = review_setup
    item = await service.enqueue(submission.id)
    session = RecordingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    readable = readable_bot(public_review=not private_review)
    bot.get_chat = readable.get_chat
    bot.get_chat_member = readable.get_chat_member
    app = create_bot_application(
        configured(channel_id=str(DESTINATION)),
        bot=bot,
        persistence_unit_of_work=database.unit_of_work,
    )
    recovered = AsyncMock()

    async def recovery_probe(**kwargs):
        await recovered()

    app.dispatcher.startup.register(recovery_probe)

    async def poll(*args, **kwargs):
        await app.dispatcher.emit_startup(bot=bot)
        for number in (1, 2):
            await app.dispatcher.feed_update(
                bot,
                Update(
                    update_id=number,
                    callback_query=CallbackQuery(
                        id=str(number),
                        from_user=User(id=42, is_bot=False, first_name="Fixture"),
                        chat_instance="fixture",
                        data=f"reviewreject:{item.id}:1",
                        message=Message(
                            message_id=99,
                            date=datetime.now(UTC),
                            chat=Chat(id=CHAT, type="channel"),
                        ),
                    ),
                ),
            )

    app.dispatcher.start_polling = AsyncMock(side_effect=poll)
    if private_review:
        await app.start_polling()
        recovered.assert_awaited_once()
        await assert_rejected_without_effects(database, submission, service, item.id)
    else:
        with pytest.raises(MediaError) as error:
            await app.start_polling()
        assert error.value.code == "review_permissions_unverified"
        recovered.assert_not_awaited()
        app.dispatcher.start_polling.assert_not_awaited()
        assert (await service.get(item.id)).decision_state == "pending"
    assert not any(isinstance(method, SendVideo) for method in session.methods)
