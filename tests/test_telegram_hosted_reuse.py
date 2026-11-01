"""Hosted media uses Telegram references, never download or decoding."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.types import Video
from test_reply_chains import chain_database as _chain_database

from cats_channel.adapters.aiogram_publisher import AiogramPublisher
from cats_channel.bot.telegram_media import TelegramHostedMediaAdapter
from cats_channel.config import Settings
from cats_channel.errors import MediaError
from cats_channel.persistence import TelegramMessageRef
from cats_channel.publication.errors import DeliveryRejected

chain_database = _chain_database


def incoming(**changes):
    return Video(
        **{
            "file_id": "received-by-bot",
            "file_unique_id": "stable",
            "width": 640,
            "height": 360,
            "duration": 30,
            "file_size": 30_000_000,
        }
        | changes
    )


def bot():
    return SimpleNamespace(
        id=123,
        get_file=AsyncMock(side_effect=AssertionError("getFile forbidden")),
        download=AsyncMock(side_effect=AssertionError("download forbidden")),
        send_video=AsyncMock(
            return_value=SimpleNamespace(chat=SimpleNamespace(id=-100123), message_id=10)
        ),
    )


async def test_above_download_limit_is_admitted_without_byte_inspection():
    client = bot()
    decoder = Mock(side_effect=AssertionError("decode forbidden"))
    media = await TelegramHostedMediaAdapter(Settings(_env_file=None), validator=decoder).acquire(
        client, incoming(), TelegramMessageRef(42, 1)
    )
    evidence = media.validation.to_record()
    assert evidence["validator"] == "telegram_metadata"
    assert evidence["full_decode"] is False and evidence["sha256"] is None
    assert evidence["bot_id"] == client.id and evidence["size_bytes"] == 30_000_000
    assert "video_stream_count" not in evidence
    client.get_file.assert_not_awaited()
    client.download.assert_not_awaited()
    decoder.assert_not_called()
    submission = SimpleNamespace(
        status="validated",
        validation_evidence=evidence,
        media_origin="telegram_native",
        source_provider="telegram",
        source_media_id="stable",
        provenance={
            "media": media.provenance,
            "telegram": {"file_id": media.file_id, "file_unique_id": media.file_unique_id},
        },
    )
    publisher = AiogramPublisher(client, Settings(_env_file=None), destination_chat_id=-100123)
    parent = TelegramMessageRef(-100123, 7)
    await publisher.send(submission, parent=parent)
    args = client.send_video.await_args
    assert args.args[1] == "received-by-bot"
    assert args.kwargs["reply_parameters"].message_id == 7
    assert args.kwargs["reply_parameters"].allow_sending_without_reply is False
    client.get_file.assert_not_awaited()
    submission.validation_evidence = {**evidence, "bot_id": 999}
    with pytest.raises(DeliveryRejected):
        await publisher.send(submission, parent=parent)
    client.send_video.assert_awaited_once()


@pytest.mark.parametrize(
    "changes",
    [
        {"file_size": None},
        {"file_size": 0},
        {"file_size": 50_000_000},
        {"duration": 0},
        {"duration": 301},
        {"width": 0},
        {"height": 0},
    ],
)
async def test_metadata_policy_rejects_without_network(changes):
    client = bot()
    with pytest.raises(MediaError):
        await TelegramHostedMediaAdapter(Settings(_env_file=None)).acquire(
            client, incoming(**changes), TelegramMessageRef(42, 1)
        )
    client.get_file.assert_not_awaited()
    client.download.assert_not_awaited()


async def test_dispatcher_persists_metadata_then_real_approval_publishes_once(chain_database):
    from aiogram import Bot
    from aiogram.methods import GetFile, SendVideo
    from test_aiogram_publisher import PublishingSession
    from test_bot_submission_intake import message_update
    from test_publication import DESTINATION, pending, publisher

    from cats_channel.bot.application import create_bot_application

    class NoDownloadSession(PublishingSession):
        async def make_request(self, bot, method, timeout=None):
            assert not isinstance(method, GetFile)
            result = await super().make_request(bot, method, timeout)
            if isinstance(method, SendVideo):
                return result.model_copy(
                    update={"chat": result.chat.model_copy(update={"id": int(method.chat_id)})}
                )
            return result

        async def stream_content(self, *args, **kwargs):
            raise AssertionError("Download forbidden")
            yield b""

    db = chain_database
    root_service = publisher(db)
    submission, _intent = await pending(db, root_service)
    root = await root_service.approve_pilot(submission.id)
    session = NoDownloadSession()
    client = Bot("123456:TEST_TOKEN", session=session)
    config = Settings(
        _env_file=None,
        bot_token="123456:TEST_TOKEN",
        admin_user_id=42,
        channel_id=str(DESTINATION),
        review_channel_id=-100456,
    )
    app = create_bot_application(config, bot=client, persistence_unit_of_work=db.unit_of_work)
    try:
        await app.dispatcher.feed_update(
            client, message_update(text=f"/start catreply_{root_service.transport.markup[0][1]}")
        )
        await app.dispatcher.feed_update(client, message_update(update_id=2, video=incoming()))
        async with db.unit_of_work() as uow:
            projection = await uow.projections.get_by_reference(TelegramMessageRef(42, 2))
            accepted = await uow.submissions.get(projection.submission_id)
            review = await uow.reviews.for_submission(accepted.id, -100456)
        assert accepted.validation_evidence["full_decode"] is False
        assert accepted.validation_evidence["sha256"] is None
        assert review.delivery_state == "confirmed" and review.decision_state == "pending"
        service = app.dispatcher.workflow_data["review_service"]
        result = await service.approve(
            review.id, review.version, actor_id=42, chat_id=-100456, message_id=review.message_id
        )
        assert result.decision_state == "approved"
        await service.approve(
            review.id, review.version, actor_id=42, chat_id=-100456, message_id=review.message_id
        )
        sends = [m for m in session.methods if isinstance(m, SendVideo)]
        assert len(sends) == 2
        assert "metadata only" in sends[0].caption
        async with db.unit_of_work() as uow:
            thread = await uow.threads.get(accepted.thread_id)
            assert thread.tail_post_id == root.post_id
        assert sends[-1].reply_parameters.message_id == 1
        assert all(m.video == "received-by-bot" for m in sends)
    finally:
        await client.session.close()


@pytest.mark.parametrize(
    "damage", ["local", "digest", "decode", "bot", "size", "duration", "missing_bot"]
)
async def test_metadata_evidence_cannot_bypass_publisher_policy(damage):
    client = bot()
    media = await TelegramHostedMediaAdapter(Settings(_env_file=None)).acquire(
        client, incoming(), TelegramMessageRef(42, 1)
    )
    evidence = media.validation.to_record()
    origin = "telegram_native"
    if damage == "local":
        origin = "local_library"
    if damage == "digest":
        evidence["sha256"] = "a" * 64
    if damage == "decode":
        evidence["full_decode"] = True
    if damage == "bot":
        evidence["bot_id"] = 999
    if damage == "size":
        evidence["size_bytes"] = 50_000_000
    if damage == "duration":
        evidence["duration_seconds"] = 301
    if damage == "missing_bot":
        del evidence["bot_id"]
    submission = SimpleNamespace(
        status="validated",
        validation_evidence=evidence,
        media_origin=origin,
        source_provider="telegram",
        source_media_id="stable",
        provenance={
            "media": {"adapter": "telegram_native"},
            "telegram": {"file_id": "received-by-bot", "file_unique_id": "stable"},
        },
    )
    with pytest.raises(DeliveryRejected):
        await AiogramPublisher(client, Settings(_env_file=None), destination_chat_id=-100123).send(
            submission, parent=None
        )
    client.send_video.assert_not_awaited()
    client.get_file.assert_not_awaited()
