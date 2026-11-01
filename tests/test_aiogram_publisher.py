"""Production Bot API mapping and real dispatcher pilot path with fake network."""

import hashlib
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    EditMessageReplyMarkup,
    GetFile,
    SendDocument,
    SendMessage,
    SendVideo,
)
from aiogram.types import File
from test_bot_application import RecordingSession, sent_texts, settings, update
from test_submission_contracts import library_item

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from cats_channel.adapters.aiogram_publisher import AiogramPublisher, destination_link
from cats_channel.bot import create_bot_application
from cats_channel.diagnostics import configure_logging
from cats_channel.persistence import Database, TelegramMessageRef
from cats_channel.publication.errors import DeliveryRejected
from cats_channel.submissions import (
    LibraryManifestSourceResolver,
    SubmissionRequest,
    SubmissionService,
    local_media_from_library_item,
)

DEST = -100123456789


class PublishingSession(RecordingSession):
    def __init__(self):
        super().__init__()
        self.rejected = False

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetFile):
            self.methods.append(method)
            return File(
                file_id="bot-file", file_unique_id="native-unique", file_path="video/file.mp4"
            )
        if isinstance(method, (SendVideo, SendDocument)):
            if self.rejected:
                self.methods.append(method)
                raise TelegramBadRequest(method=method, message="reply message not found")
            message = await super().make_request(bot, method, timeout)
            return message.model_copy(
                update={"chat": message.chat.model_copy(update={"id": DEST, "type": "channel"})}
            )
        return await super().make_request(bot, method, timeout)


async def local_submission(db, tmp_path, *, suffix=".mp4"):
    item = library_item(tmp_path)
    folder = tmp_path / "library/youtube/abcdefghijk"
    folder.mkdir(parents=True)
    path = folder / ("media" + suffix)
    path.write_bytes(b"validated")
    item.manifest["file"].update(name=path.name, sha256=hashlib.sha256(b"validated").hexdigest())
    (folder / "manifest.json").write_text(json.dumps(item.manifest))
    item = replace(item, media_path=path)
    result = await SubmissionService(db.unit_of_work, LibraryManifestSourceResolver()).submit(
        SubmissionRequest(local_media_from_library_item(item))
    )
    async with db.unit_of_work() as uow:
        return await uow.submissions.get(result.submission_id)


@pytest.fixture
async def db(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'publisher.sqlite3').as_posix()}")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


@pytest.mark.parametrize("suffix,method_type", [(".mp4", SendVideo), (".webm", SendDocument)])
async def test_trusted_local_media_clean_caption_and_exact_reply(db, tmp_path, suffix, method_type):
    submission = await local_submission(db, tmp_path, suffix=suffix)
    session = PublishingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    adapter = AiogramPublisher(bot, settings(download_dir=tmp_path), destination_chat_id=DEST)
    parent = TelegramMessageRef(DEST, 9)
    assert (await adapter.send(submission, parent=parent)).chat_id == DEST
    send = session.methods[-1]
    assert isinstance(send, method_type)
    assert send.caption is None
    assert send.reply_parameters.message_id == 9
    assert send.reply_parameters.allow_sending_without_reply is False
    assert (send.video if isinstance(send, SendVideo) else send.document).data == b"validated"
    await bot.session.close()


@pytest.mark.parametrize("damage", ["corrupt", "missing", "untrusted", "cross_chat"])
async def test_media_preflight_rejects_without_send(db, tmp_path, damage):
    submission = await local_submission(db, tmp_path)
    if damage == "corrupt":
        (tmp_path / "library/youtube/abcdefghijk/media.mp4").write_bytes(b"corrupt")
    elif damage == "missing":
        (tmp_path / "library/youtube/abcdefghijk/media.mp4").unlink()
    elif damage == "untrusted":
        submission = replace(submission, provenance={"media": {"library_item_path": "../private"}})
    bot = Bot("123456:TEST_TOKEN", session=PublishingSession())
    adapter = AiogramPublisher(bot, settings(download_dir=tmp_path), destination_chat_id=DEST)
    with pytest.raises(DeliveryRejected):
        await adapter.send(
            submission, parent=TelegramMessageRef(-100999, 1) if damage == "cross_chat" else None
        )
    assert not bot.session.methods


async def test_native_file_reuses_hosted_id_without_getfile_or_reply_fallback(db, tmp_path):
    local = await local_submission(db, tmp_path)
    native = replace(
        local,
        media_origin="telegram_native",
        source_provider="telegram",
        source_media_id="native-unique",
        provenance={
            "media": {"adapter": "telegram_native"},
            "telegram": {"file_id": "bot-file", "file_unique_id": "native-unique"},
        },
    )
    session = PublishingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    adapter = AiogramPublisher(bot, settings(), destination_chat_id=DEST)
    await adapter.send(native, parent=None)
    assert not any(isinstance(method, GetFile) for method in session.methods)
    assert session.methods[0].video == "bot-file" and session.methods[0].reply_parameters is None
    session.rejected = True
    with pytest.raises(DeliveryRejected):
        await adapter.send(native, parent=TelegramMessageRef(DEST, 999))
    assert len([m for m in session.methods if isinstance(m, SendVideo)]) == 2
    with pytest.raises(DeliveryRejected):
        await adapter.send(replace(native, source_media_id="foreign"), parent=None)
    assert len([m for m in session.methods if isinstance(m, SendVideo)]) == 2


async def test_dispatcher_intake_approval_projection_button_and_duplicate(db, tmp_path, capsys):
    # Real /post intake, application service, production adapter, fake Bot API session.
    session = PublishingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    item = library_item(tmp_path)
    folder = tmp_path / "library/youtube/abcdefghijk"
    folder.mkdir(parents=True)
    path = folder / "media.mp4"
    path.write_bytes(b"validated")
    item.manifest["file"]["sha256"] = hashlib.sha256(b"validated").hexdigest()
    (folder / "manifest.json").write_text(json.dumps(item.manifest))
    item = replace(item, media_path=path)
    media = AsyncMock()
    media.acquire_async.return_value = item
    app = create_bot_application(
        settings(download_dir=tmp_path),
        bot=bot,
        media_service=media,
        persistence_unit_of_work=db.unit_of_work,
        logger=configure_logging("INFO"),
        correlation_id_factory=lambda: "approval-log-1",
    )
    await app.dispatcher.feed_update(bot, update("/post"))
    await app.dispatcher.feed_update(bot, update("https://youtu.be/abcdefghijk", update_id=2))
    async with db.unit_of_work() as uow:
        submission = await uow.submissions.get_by_source_media("youtube", "abcdefghijk")
        assert submission is not None
        assert await uow.threads.get_post_for_submission(submission.id) is None
    for n in (3, 4):
        await app.dispatcher.feed_update(
            bot, update(f"/pilot_publish {submission.id}", update_id=n)
        )
    assert len([m for m in session.methods if isinstance(m, SendVideo)]) == 1
    edits = [m for m in session.methods if isinstance(m, EditMessageReplyMarkup)]
    assert len(edits) == 1
    button = edits[0].reply_markup.inline_keyboard[0][0]
    assert button.text == "Reply with a cat" and "?start=catreply_" in button.url
    raw = button.url.split("catreply_")[1]
    # Existing resolver contract proves that this is a usable exact-post token.
    # Resolve through the public chain token repository below; never inspect raw SQL tokens.
    from cats_channel.reply_chains.service import token_digest

    target = await app.dispatcher.workflow_data["reply_target_resolver"].resolve(raw, actor_id=42)
    assert target is not None

    async with db.unit_of_work() as uow:
        token = await uow.reply_tokens.get(token_digest(raw))
        post = await uow.threads.get_post_for_submission(submission.id)
        assert target.post_id == post.id
        assert token.post_id == post.id
        assert (await uow.publications.get_for_post(post.id, DEST)).state == "confirmed"
        assert await uow.projections.get_destination(post_id=post.id, chat_id=DEST)
    assert any("confirmed" in (m.text or "") for m in session.methods if isinstance(m, SendMessage))
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    completions = [
        record
        for record in records
        if record["event"] == "bot_operation_finished" and record["operation"] == "pilot_publish"
    ]
    assert len(completions) == 2
    assert all(
        record["outcome"] == record["publication_state"] == "confirmed" for record in completions
    )
    assert (
        len([record for record in records if record["event"] == "publication_operation_finished"])
        == 2
    )
    await bot.session.close()


async def test_ineligible_pilot_has_matching_failure_and_completion_logs(db, capsys):
    session = PublishingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    app = create_bot_application(
        settings(),
        bot=bot,
        persistence_unit_of_work=db.unit_of_work,
        logger=configure_logging("INFO"),
        correlation_id_factory=lambda: "approval-error-1",
    )

    await app.dispatcher.feed_update(
        bot, update("/pilot_publish 00000000-0000-4000-8000-000000000001")
    )

    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    failure = next(record for record in records if record["event"] == "bot_publication_failure")
    completion = next(record for record in records if record["event"] == "bot_operation_finished")
    assert failure["code"] == completion["error_category"] == "publication_not_eligible"
    assert failure["correlation_id"] == completion["correlation_id"] == "approval-error-1"
    assert completion["operation"] == "pilot_publish"
    assert completion["outcome"] == "error"
    assert any("not eligible" in text for text in sent_texts(session))
    assert not any(isinstance(method, (SendVideo, SendDocument)) for method in session.methods)
    await bot.session.close()


@pytest.mark.parametrize("user_id,chat_type", [(99, "private"), (42, "group")])
async def test_pilot_authorization(db, user_id, chat_type):
    session = PublishingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    app = create_bot_application(settings(), bot=bot, persistence_unit_of_work=db.unit_of_work)
    await app.dispatcher.feed_update(
        bot, update("/pilot_publish invalid", user_id=user_id, chat_type=chat_type)
    )
    assert not session.methods


@pytest.mark.parametrize(
    "command",
    [
        "/pilot_publish",
        "/pilot_publish invalid",
        "/pilot_publish 00000000-0000-4000-8000-000000000001",
    ],
)
async def test_invalid_pilot_requests_never_send(db, command):
    session = PublishingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    app = create_bot_application(settings(), bot=bot, persistence_unit_of_work=db.unit_of_work)
    await app.dispatcher.feed_update(bot, update(command))
    assert not any(isinstance(m, (SendVideo, SendDocument)) for m in session.methods)
    assert isinstance(session.methods[-1], SendMessage)


def test_navigation_link_supported_coordinates():
    assert destination_link(TelegramMessageRef(DEST, 7)) == "https://t.me/c/123456789/7"
    assert destination_link(TelegramMessageRef(42, 7)) is None


async def test_adapter_installs_only_destination_navigation_links():
    from cats_channel.reply_tokens import new_reply_token

    session = PublishingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    adapter = AiogramPublisher(bot, settings(), destination_chat_id=DEST)
    await adapter.install_markup(
        TelegramMessageRef(DEST, 1), token=new_reply_token(), child=TelegramMessageRef(DEST, 7)
    )
    edit = session.methods[-1]
    assert isinstance(edit, EditMessageReplyMarkup)
    assert edit.reply_markup.inline_keyboard[1][0].url == "https://t.me/c/123456789/7"
    count = len(session.methods)
    with pytest.raises(DeliveryRejected):
        await adapter.install_markup(
            TelegramMessageRef(DEST, 1), token=new_reply_token(), child=TelegramMessageRef(42, 7)
        )
    assert len(session.methods) == count
