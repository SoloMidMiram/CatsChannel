import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cats_channel.adapters.process import CancellationToken
from cats_channel.adapters.telegram_downloader import (
    _cancellable,
    _make_client,
    _session_file,
    _session_lock,
    _telethon_proxy,
    _translate_error,
    diagnose_connection,
    download_video,
)
from cats_channel.config import Settings
from cats_channel.errors import MediaError
from cats_channel.library import store_download
from cats_channel.services.media_service import MediaService

URL = "https://youtu.be/abcdefghijk"
DATA = b"cat-video"


def settings_for(tmp_path, **overrides):
    return Settings(
        _env_file=None,
        media_backend="telegram_bot",
        telegram_api_id=123,
        telegram_api_hash="test-api-hash",
        telethon_session=tmp_path / ".secrets" / "user",
        download_dir=tmp_path / "downloads",
        **overrides,
    )


def video_message(**overrides):
    values = {
        "id": 31,
        "sender_id": 10,
        "out": False,
        "reply_to_msg_id": 30,
        "buttons": None,
        "document": SimpleNamespace(mime_type="video/mp4", size=len(DATA)),
        "file": SimpleNamespace(ext=".mp4"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def fake_client(responses):
    conversation = AsyncMock()
    conversation.__aenter__.return_value = conversation
    conversation.send_message.return_value = SimpleNamespace(id=30)
    conversation.get_response.side_effect = responses
    client = SimpleNamespace(
        connect=AsyncMock(),
        disconnect=AsyncMock(),
        is_user_authorized=AsyncMock(return_value=True),
        get_me=AsyncMock(return_value=SimpleNamespace(bot=False)),
        get_entity=AsyncMock(return_value=SimpleNamespace(id=10, bot=True)),
        conversation=lambda *_args, **_kwargs: conversation,
    )

    async def transfer(_message, *, file, progress_callback):
        Path(file).write_bytes(DATA)
        await progress_callback(len(DATA), len(DATA))
        return file

    client.download_media = AsyncMock(side_effect=transfer)
    return client, conversation


def create_fake_session(settings):
    session = _session_file(settings)
    session.parent.mkdir(parents=True)
    session.write_bytes(b"fake session fixture; no real credentials")


def test_telegram_proxy_is_explicitly_passed_to_telethon(tmp_path):
    settings = settings_for(tmp_path, telegram_proxy="socks5h://127.0.0.1:10808")
    assert _telethon_proxy(settings) == {
        "proxy_type": "socks5",
        "addr": "127.0.0.1",
        "port": 10808,
        "rdns": True,
    }
    with patch("telethon.TelegramClient") as client:
        _make_client(settings)
    assert client.call_args.kwargs["proxy"] == _telethon_proxy(settings)


def test_telegram_proxy_is_not_inherited_implicitly(tmp_path):
    settings = settings_for(tmp_path, youtube_proxy="socks5h://127.0.0.1:10808")
    assert _telethon_proxy(settings) is None
    with patch("telethon.TelegramClient") as client:
        _make_client(settings)
    assert client.call_args.kwargs["proxy"] is None


@pytest.mark.parametrize(
    ("exception_name", "code"),
    [
        ("ApiIdInvalidError", "telegram_api_credentials"),
        ("PhoneNumberFloodError", "telegram_flood_wait"),
        ("PhoneNumberInvalidError", "telegram_phone"),
        ("PhoneCodeExpiredError", "telegram_login_code"),
        ("PasswordHashInvalidError", "telegram_password"),
        ("ProxyConnectionError", "telegram_connect"),
        ("UnexpectedTelegramError", "telegram_download"),
    ],
)
def test_login_error_classification_is_specific_and_secret_safe(exception_name, code):
    error_type = type(exception_name, (Exception,), {})
    translated = _translate_error(error_type("private account detail"), phase="login")
    assert translated.code == code
    assert translated.log_analysis["phase"] == "login"
    assert translated.log_analysis["primary"] == code
    assert translated.log_analysis["exception_types"] == [exception_name]
    assert translated.log_analysis["raw_log_included"] is False
    assert "private" not in str(translated)


def test_telegram_video_uses_no_youtube_extractor_and_records_receipt(tmp_path):
    settings = settings_for(tmp_path)
    create_fake_session(settings)
    client, conversation = fake_client([video_message()])
    playback = {
        "status": "passed",
        "full_decode": "passed",
        "duration_seconds": 12,
        "width": 360,
        "height": 640,
        "video_codec": "h264",
    }
    with (
        patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client),
        patch("cats_channel.adapters.telegram_downloader.shutil.which", return_value="binary"),
        patch("cats_channel.library._probe_media", return_value=playback) as validation,
        patch("cats_channel.library.download") as youtube,
    ):
        result = store_download(settings, URL)
        existing = store_download(settings, URL)
    assert result["status"] == "stored" and existing["status"] == "existing"
    youtube.assert_not_called()
    conversation.send_message.assert_awaited_once_with(
        "https://www.youtube.com/watch?v=abcdefghijk"
    )
    validation.assert_called_once()
    client.disconnect.assert_awaited_once()
    manifest = result["manifest"]
    assert manifest["metadata"]["duration"] == 12
    assert manifest["download_policy"]["yt_dlp_version"] is None
    assert manifest["acquisition"]["receipt"]["source_identity_verified"] is False
    assert manifest["acquisition"]["receipt"]["response_message_id"] == 31
    assert "_telegram_receipt" not in manifest["metadata"]
    assert list((settings.download_dir / ".staging").iterdir()) == []
    assert not Path(f"{_session_file(settings)}.lock").exists()


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (
            video_message(document=SimpleNamespace(mime_type="audio/mpeg", size=9)),
            "telegram_bot_flow",
        ),
        (video_message(document=None, buttons=[["choose"]]), "telegram_bot_flow"),
        (
            video_message(document=SimpleNamespace(mime_type="video/mp4", size=46 * 1024 * 1024)),
            "upload_limit",
        ),
    ],
)
def test_rejects_wrong_flow_or_oversize_before_transfer(tmp_path, message, code):
    settings = settings_for(tmp_path)
    create_fake_session(settings)
    client, _conversation = fake_client([message])
    with (
        patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client),
        patch("cats_channel.adapters.telegram_downloader.shutil.which", return_value="binary"),
        pytest.raises(MediaError) as error,
    ):
        store_download(settings, URL)
    assert error.value.code == code
    client.download_media.assert_not_awaited()
    client.disconnect.assert_awaited_once()
    assert list((settings.download_dir / ".staging").iterdir()) == []
    assert not (settings.download_dir / "library/youtube/abcdefghijk").exists()


def test_ignores_progress_and_wrong_sender_without_resending(tmp_path):
    settings = settings_for(tmp_path)
    create_fake_session(settings)
    progress = video_message(document=None)
    unrelated = video_message(sender_id=999)
    client, conversation = fake_client([progress, unrelated, video_message(reply_to_msg_id=None)])
    metadata = {}
    with (
        patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client),
        patch("cats_channel.adapters.telegram_downloader.shutil.which", return_value="binary"),
    ):
        path = download_video(settings, URL, tmp_path, metadata_out=metadata)
    assert path.read_bytes() == DATA
    assert metadata["_telegram_receipt"]["correlation"] == "serialized_conversation"
    conversation.send_message.assert_awaited_once()


def test_missing_session_fails_before_connect(tmp_path):
    settings = settings_for(tmp_path)
    with (
        patch("cats_channel.adapters.telegram_downloader._make_client") as factory,
        patch("cats_channel.adapters.telegram_downloader.shutil.which", return_value="binary"),
        pytest.raises(MediaError) as error,
    ):
        download_video(settings, URL, tmp_path, metadata_out={})
    assert error.value.code == "telegram_login"
    factory.assert_not_called()


async def test_connection_diagnosis_is_one_attempt_read_only_and_secret_safe(tmp_path):
    settings = settings_for(tmp_path, telegram_proxy="socks5h://127.0.0.1:10808")
    create_fake_session(settings)
    client, conversation = fake_client([])
    with patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client):
        report = await diagnose_connection(settings)
    assert report["status"] == "ok"
    assert report["connection"] == "passed"
    assert report["authorization"] == "passed"
    assert report["connection_attempts"] == 1
    assert report["automatic_retries"] == 0
    assert report["completed_phases"] == ["connection", "authorization", "disconnect"]
    assert report["proxy_configured"] is True
    assert report["proxy_scheme"] == "socks5h"
    client.connect.assert_awaited_once()
    client.is_user_authorized.assert_awaited_once()
    client.disconnect.assert_awaited_once()
    client.get_me.assert_not_awaited()
    client.get_entity.assert_not_awaited()
    conversation.send_message.assert_not_awaited()
    assert "test-api-hash" not in str(report)
    assert str(tmp_path) not in str(report)


async def test_connection_diagnosis_reports_unauthorized_without_prompt_or_message(tmp_path):
    settings = settings_for(tmp_path)
    create_fake_session(settings)
    client, conversation = fake_client([])
    client.is_user_authorized.return_value = False
    client.start = AsyncMock(side_effect=AssertionError("diagnosis must never prompt"))
    with patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client):
        report = await diagnose_connection(settings)
    assert report["status"] == "error"
    assert report["error"]["code"] == "telegram_login"
    assert report["failed_phase"] == "authorization"
    assert report["automatic_retries"] == 0
    assert report["log_analysis"]["raw_log_included"] is False
    client.start.assert_not_awaited()
    client.get_entity.assert_not_awaited()
    conversation.send_message.assert_not_awaited()


async def test_connection_diagnosis_classifies_proxy_failure_without_raw_log(tmp_path):
    settings = settings_for(tmp_path)
    create_fake_session(settings)
    client, _conversation = fake_client([])
    proxy_error = type("ProxyConnectionError", (Exception,), {})
    client.connect.side_effect = proxy_error("socks5h://private:secret@host:10808")
    with patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client):
        report = await diagnose_connection(settings)
    assert report["status"] == "error"
    assert report["error"]["code"] == "telegram_connect"
    assert report["failed_phase"] == "connection"
    assert report["connection_attempts"] == 1
    assert report["automatic_retries"] == 0
    assert report["log_analysis"]["exception_types"] == ["ProxyConnectionError"]
    assert "private" not in str(report)


def test_same_session_alias_uses_same_exclusive_lock(tmp_path):
    settings = settings_for(tmp_path)
    alias = settings.model_copy(update={"telethon_session": _session_file(settings)})
    with _session_lock(settings), pytest.raises(MediaError) as error, _session_lock(alias):
        pytest.fail("Concurrent sessions must be rejected")
    assert error.value.code == "telegram_busy"


def test_invalid_url_does_not_create_client(tmp_path):
    with (
        patch("cats_channel.adapters.telegram_downloader._make_client") as factory,
        pytest.raises(ValueError),
    ):
        download_video(settings_for(tmp_path), "https://example.com/", tmp_path, metadata_out={})
    factory.assert_not_called()


async def test_cancellation_drains_operation():
    token = CancellationToken()
    finished = asyncio.Event()

    async def pending():
        try:
            token.cancel()
            await asyncio.sleep(10)
        finally:
            finished.set()

    with pytest.raises(MediaError) as error:
        await _cancellable(pending(), token, 5)
    assert error.value.code == "cancelled"
    assert finished.is_set()


async def test_timeout_drains_operation():
    finished = asyncio.Event()

    async def pending():
        try:
            await asyncio.sleep(10)
        finally:
            finished.set()

    with pytest.raises(MediaError) as error:
        await _cancellable(pending(), None, 0.02)
    assert error.value.code == "timeout"
    assert finished.is_set()


def test_bot_errors_are_secret_safe(tmp_path):
    settings = settings_for(tmp_path)
    create_fake_session(settings)
    client, _ = fake_client([])
    client.connect.side_effect = RuntimeError("session contents and phone number")
    with (
        patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client),
        patch("cats_channel.adapters.telegram_downloader.shutil.which", return_value="binary"),
        pytest.raises(MediaError) as error,
    ):
        download_video(settings, URL, tmp_path, metadata_out={})
    assert error.value.code == "telegram_download"
    assert "phone" not in str(error.value)
    assert "test-api-hash" not in repr(settings)
    client.disconnect.assert_awaited_once()


def test_telegram_probe_does_not_contact_youtube(tmp_path):
    with (
        patch("cats_channel.services.media_service.probe_media") as youtube,
        pytest.raises(MediaError) as error,
    ):
        MediaService(settings_for(tmp_path)).probe(URL)
    assert error.value.code == "backend_capability"
    youtube.assert_not_called()


@pytest.mark.parametrize("action", ["--probe", "--diagnose"])
def test_cli_telegram_probe_is_local_and_explicit(tmp_path, monkeypatch, capsys, action):
    import json

    from cats_channel.cli import main

    monkeypatch.setattr("sys.argv", ["cats-channel", action, URL])
    with (
        patch("cats_channel.cli.Settings", return_value=settings_for(tmp_path)),
        patch("cats_channel.cli.probe") as youtube,
        patch("cats_channel.cli.diagnostic_manifest") as diagnose,
    ):
        assert main() == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "backend_capability"
    youtube.assert_not_called()
    diagnose.assert_not_called()


def test_cli_telegram_diagnose_preserves_manifest_and_exit_status(tmp_path, monkeypatch, capsys):
    import json

    from cats_channel.cli import main

    report = {
        "status": "error",
        "error": {"code": "telegram_connect"},
        "connection_attempts": 1,
        "automatic_retries": 0,
    }
    monkeypatch.setattr("sys.argv", ["cats-channel", "--telegram-diagnose"])
    with (
        patch("cats_channel.cli.Settings", return_value=settings_for(tmp_path)),
        patch(
            "cats_channel.adapters.telegram_downloader.diagnose_connection",
            new=AsyncMock(return_value=report),
        ) as diagnose,
    ):
        assert main() == 1
    assert json.loads(capsys.readouterr().out) == report
    diagnose.assert_awaited_once()


def test_disconnect_failure_preserves_safe_primary_error(tmp_path):
    settings = settings_for(tmp_path)
    create_fake_session(settings)
    client, _ = fake_client([])
    client.connect.side_effect = RuntimeError("private transport error")
    client.disconnect.side_effect = RuntimeError("private account details")
    with (
        patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client),
        patch("cats_channel.adapters.telegram_downloader.shutil.which", return_value="binary"),
        pytest.raises(MediaError) as error,
    ):
        download_video(settings, URL, tmp_path, metadata_out={})
    assert error.value.code == "telegram_download"
    assert error.value.warnings == ("telegram_disconnect_failed",)


def test_failed_decode_never_publishes_telegram_receipt(tmp_path):
    settings = settings_for(tmp_path)
    create_fake_session(settings)
    client, _ = fake_client([video_message()])
    with (
        patch("cats_channel.adapters.telegram_downloader._make_client", return_value=client),
        patch("cats_channel.adapters.telegram_downloader.shutil.which", return_value="binary"),
        patch("cats_channel.library._probe_media", side_effect=MediaError(code="media_validation")),
        pytest.raises(MediaError) as error,
    ):
        store_download(settings, URL)
    assert error.value.code == "media_validation"
    assert list((settings.download_dir / ".staging").iterdir()) == []
    assert not (settings.download_dir / "library/youtube/abcdefghijk").exists()


@pytest.mark.parametrize(
    ("primary", "code"),
    [
        (KeyboardInterrupt(), "cancelled"),
        (asyncio.CancelledError(), "cancelled"),
        (OSError("private path and credential"), "local_io"),
        (ValueError("private input"), "invalid_url"),
        (RuntimeError("private account information"), "internal_error"),
    ],
)
def test_session_cleanup_failure_preserves_primary_classification(tmp_path, primary, code):
    settings = settings_for(tmp_path)
    with (
        patch.object(Path, "unlink", side_effect=OSError("private lock path")),
        pytest.raises(MediaError) as raised,
        _session_lock(settings),
    ):
        raise primary
    assert raised.value.code == code
    assert raised.value.warnings == ("session_lock_cleanup_failed",)
    assert "private" not in str(raised.value)


def test_session_cleanup_keeps_existing_media_error_and_warnings(tmp_path):
    primary = MediaError(code="telegram_download", warnings=("telegram_disconnect_failed",))
    with (
        patch.object(Path, "unlink", side_effect=OSError("private lock path")),
        pytest.raises(MediaError) as raised,
        _session_lock(settings_for(tmp_path)),
    ):
        raise primary
    assert raised.value is primary
    assert primary.warnings == ("telegram_disconnect_failed", "session_lock_cleanup_failed")


def test_session_cleanup_failure_after_success_reports_warning(tmp_path):
    with (
        patch.object(Path, "unlink", side_effect=OSError("private lock path")),
        pytest.raises(MediaError) as raised,
        _session_lock(settings_for(tmp_path)),
    ):
        pass
    assert raised.value.code == "cleanup_failed"
    assert raised.value.warnings == ("session_lock_cleanup_failed",)


def test_cli_interrupt_with_failed_lock_cleanup_is_safe_and_exits_130(
    tmp_path, monkeypatch, capsys
):
    import json

    from cats_channel.cli import main

    settings = settings_for(tmp_path)

    def interrupted(_url):
        with _session_lock(settings):
            raise KeyboardInterrupt("private account details")

    monkeypatch.setattr("sys.argv", ["cats-channel", "--download", URL])
    with (
        patch("cats_channel.cli.Settings", return_value=settings),
        patch("cats_channel.cli.MediaService.acquire", side_effect=interrupted),
        patch.object(Path, "unlink", side_effect=OSError("private lock path")),
    ):
        assert main() == 130
    output = capsys.readouterr().out
    record = json.loads(output)
    assert record["error"]["code"] == "cancelled"
    assert record["warnings"] == ["session_lock_cleanup_failed"]
    assert "private" not in output


@pytest.mark.parametrize(
    ("installed", "credentials", "session", "ffmpeg", "ffprobe"),
    [
        (True, True, True, True, True),
        (False, True, True, True, True),
        (True, False, True, True, True),
        (True, True, False, True, True),
        (True, True, True, False, True),
        (True, True, True, True, False),
    ],
)
def test_telegram_doctor_readiness_is_offline_and_secret_safe(
    tmp_path, installed, credentials, session, ffmpeg, ffprobe
):
    import json
    from importlib.metadata import PackageNotFoundError

    from cats_channel.media import runtime_report

    settings = settings_for(tmp_path).model_copy(
        update={
            "youtube_cookie_file": tmp_path / "private-youtube-cookies.txt",
        }
    )
    if not credentials:
        settings = settings.model_copy(update={"telegram_api_id": None})
    if session:
        create_fake_session(settings)

    def package_version(name):
        assert name == "telethon", "Telegram doctor must not inspect yt-dlp packages"
        if not installed:
            raise PackageNotFoundError(name)
        return "1.45.0"

    def executable(name):
        return name if {"ffmpeg": ffmpeg, "ffprobe": ffprobe}[name] else None

    with (
        patch("cats_channel.media.version", side_effect=package_version),
        patch("cats_channel.media.shutil.which", side_effect=executable),
        patch("cats_channel.media._cookie_health") as cookie_check,
        patch("cats_channel.adapters.telegram_downloader._make_client") as factory,
        patch.object(Path, "open", side_effect=AssertionError("Do not open a session or jar")),
    ):
        report = runtime_report(settings)
    assert report["telethon_installed"] == installed
    assert report["telegram_api_credentials_configured"] == credentials
    assert report["telegram_session_file_present"] == session
    assert report["telegram_downloader_bot"] == "whatsmusicbot"
    assert report["telegram_backend_ready"] == all(
        (installed, credentials, session, ffmpeg, ffprobe)
    )
    assert report["readiness_scope"] == "offline_configuration"
    assert report["telegram_session_authorization"] == "not_checked"
    assert report["cookie_handling"] == "not_used"
    assert not any(key.startswith(("youtube_", "cookie_file_")) for key in report)
    serialized = json.dumps(report)
    assert "test-api-hash" not in serialized
    assert str(tmp_path) not in serialized
    cookie_check.assert_not_called()
    factory.assert_not_called()


def test_telegram_doctor_contains_session_stat_failure(tmp_path):
    from cats_channel.media import runtime_report

    with (
        patch("cats_channel.media.version", return_value="1.45.0"),
        patch("cats_channel.media.shutil.which", return_value="tool"),
        patch.object(Path, "is_file", side_effect=PermissionError("private session location")),
    ):
        report = runtime_report(settings_for(tmp_path))
    assert report["telegram_session_check_error"] is True
    assert report["telegram_session_file_present"] is False
    assert report["telegram_backend_ready"] is False
    assert "private" not in str(report)
