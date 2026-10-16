import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import pytest

from cats_channel.config import Settings
from cats_channel.media import (
    MediaError,
    _analyze_extractor_log,
    diagnostic_manifest,
    download,
    media_error_report,
    probe,
    runtime_report,
    youtube_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/abcdefghijk?si=test",
        "https://www.youtube.com/shorts/abcdefghijk",
        "https://youtube.com/watch?v=abcdefghijk&list=some-playlist",
    ],
)
def test_normalizes_one_video(url):
    assert youtube_url(url) == "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=abcdefghijk",
        "http://youtu.be/abcdefghijk",
        "https://youtube.com.evil.test/watch?v=abcdefghijk",
        "https://user:secret@youtube.com/watch?v=abcdefghijk",
        "https://youtu.be:443/abcdefghijk",
        "https://youtube.com/playlist?list=test",
    ],
)
def test_rejects_non_video_or_untrusted_urls(url):
    with pytest.raises(ValueError):
        youtube_url(url)


def test_probe_returns_only_safe_metadata():
    metadata = {
        "id": "abcdefghijk",
        "title": "Cat",
        "duration": 10,
        "url": "https://signed-private-url",
        "http_headers": {"Cookie": "secret"},
    }
    result = subprocess.CompletedProcess([], 0, json.dumps(metadata), "")
    with patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result) as run:
        info = probe(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    assert "url" not in info and "http_headers" not in info
    assert "--skip-download" in run.call_args.args[0]
    assert "--abort-on-unavailable-fragments" in run.call_args.args[0]
    assert run.call_args.args[0][run.call_args.args[0].index("--concurrent-fragments") + 1] == "1"
    assert run.call_args.args[0][run.call_args.args[0].index("--sleep-requests") + 1] == "1"
    assert run.call_args.kwargs["timeout"] == 90
    assert run.call_args.args[0][run.call_args.args[0].index("--retries") + 1] == "0"


@pytest.mark.parametrize("payload", [[], None, "metadata", {"id": "abcdefghijk"}])
def test_probe_rejects_valid_json_with_wrong_metadata_shape(payload):
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    with (
        patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result),
        pytest.raises(MediaError) as error,
    ):
        probe(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    assert error.value.code == "metadata_invalid"


def test_raw_extractor_error_is_hidden():
    result = subprocess.CompletedProcess([], 1, "", "Cookie=secret signed-url")
    with (
        patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result),
        pytest.raises(MediaError) as error,
    ):
        probe(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    assert "secret" not in str(error.value)


def test_extractor_error_gives_safe_cookie_hint():
    result = subprocess.CompletedProcess([], 1, "", "Sign in to confirm you are not a bot")
    with (
        patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result),
        pytest.raises(MediaError, match="authenticated cookies"),
    ):
        probe(Settings(_env_file=None), "https://youtu.be/abcdefghijk")


def test_pot_profile_requires_optional_plugin_before_network():
    settings = Settings(
        _env_file=None,
        youtube_profile="pot_bgutil",
        youtube_pot_provider_url="http://127.0.0.1:4416",
    )
    with (
        patch("cats_channel.media.version", side_effect=PackageNotFoundError),
        patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run") as run,
        pytest.raises(MediaError) as error,
    ):
        probe(settings, "https://youtu.be/abcdefghijk")
    run.assert_not_called()
    assert error.value.code == "profile_config"


def test_pot_profile_passes_explicit_provider_arguments():
    metadata = json.dumps({"id": "abcdefghijk", "title": "Cat", "duration": 10})
    result = subprocess.CompletedProcess([], 0, metadata, "")
    settings = Settings(
        _env_file=None,
        youtube_profile="pot_bgutil",
        youtube_pot_provider_url="http://127.0.0.1:4416",
    )
    with (
        patch("cats_channel.media.version", return_value="2.0.2"),
        patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result) as run,
    ):
        probe(settings, "https://youtu.be/abcdefghijk")
    command = run.call_args.args[0]
    extractor_args = [
        command[index + 1] for index, value in enumerate(command) if value == "--extractor-args"
    ]
    assert "youtube:player-client=mweb" in extractor_args
    assert any(
        value.startswith("youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416")
        for value in extractor_args
    )


@pytest.mark.parametrize(
    ("stderr", "code", "message"),
    [
        ("Connection timed out", "timeout", "network read or connection timeout"),
        ("OpenSSL: unexpected EOF", "network_tls", "TLS connection to YouTube failed"),
    ],
)
def test_extractor_error_gives_safe_network_hint(stderr, code, message):
    result = subprocess.CompletedProcess([], 1, "", stderr)
    with (
        patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result),
        pytest.raises(MediaError, match=message) as error,
    ):
        probe(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    assert error.value.code == code


def test_cli_interrupt_exits_cleanly(monkeypatch, capsys):
    from cats_channel.cli import main

    monkeypatch.setattr(sys, "argv", ["cats-channel", "--probe", "https://youtu.be/abcdefghijk"])
    with (
        patch("cats_channel.cli.Settings", return_value=Settings(_env_file=None)),
        patch("cats_channel.cli.probe", side_effect=KeyboardInterrupt),
    ):
        assert main() == 130
    output = json.loads(capsys.readouterr().out)
    assert output["error"]["code"] == "cancelled"


@pytest.mark.parametrize("action", ["--check", "--bot"])
def test_cli_missing_bot_configuration_is_invalid_config(action, monkeypatch, capsys):
    from cats_channel.cli import main

    monkeypatch.setattr(sys, "argv", ["cats-channel", action])
    with patch("cats_channel.cli.Settings", return_value=Settings(_env_file=None)):
        assert main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"
    assert output["error"]["code"] == "invalid_config"
    assert "token" not in json.dumps(output).lower()


def test_timeout_is_bounded():
    with (
        patch(
            "cats_channel.media.DEFAULT_PROCESS_RUNNER.run",
            side_effect=MediaError(code="timeout"),
        ),
        pytest.raises(MediaError, match="timed out") as error,
    ):
        probe(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    assert error.value.log_analysis["phase"] == "process_deadline"
    assert error.value.log_analysis["exception_types"] == ["MediaError"]


def test_cookie_source_is_never_passed_to_or_changed_by_yt_dlp(tmp_path):
    source = tmp_path / "source-cookies.txt"
    original = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\n"
    source.write_text(original)
    metadata = json.dumps({"id": "abcdefghijk", "title": "Cat", "duration": 10})
    used_cookie = None

    def fake_run(command, **_kwargs):
        nonlocal used_cookie
        used_cookie = command[command.index("--cookies") + 1]
        assert used_cookie != str(source)
        assert Path(used_cookie).read_text() == original
        Path(used_cookie).write_text("rotated by extractor")
        return subprocess.CompletedProcess(command, 0, metadata, "")

    with patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", side_effect=fake_run):
        probe(
            Settings(_env_file=None, youtube_cookie_file=source),
            "https://youtu.be/abcdefghijk",
        )

    assert source.read_text() == original
    assert used_cookie is not None and not Path(used_cookie).exists()


def test_cookie_health_is_safe_and_offline(tmp_path):
    source = tmp_path / "cookies.txt"
    source.write_bytes(
        b"# Netscape HTTP Cookie File\n"
        b".youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsecret-one\n"
        b"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1\tHSID\tsecret-two\n"
        b".example.com\tTRUE\t/\tTRUE\t0\tOTHER\tsecret-three\n"
    )
    report = runtime_report(Settings(_env_file=None, youtube_cookie_file=source))
    serialized = json.dumps(report)
    assert report["cookie_file_readable"] is True
    assert report["cookie_file_format_valid"] is True
    assert report["cookie_file_newline_style"] == "lf"
    assert report["cookie_file_entries"] == 3
    assert report["cookie_file_youtube_entries"] == 2
    assert report["cookie_file_expired_entries"] == 1
    assert report["cookie_file_session_entries"] == 1
    assert "SID" not in serialized
    assert "secret" not in serialized


@pytest.mark.parametrize(
    ("newline", "style"),
    [(b"\n", "lf"), (b"\r\n", "crlf")],
)
def test_cookie_health_detects_explicit_byte_newlines(tmp_path, newline, style):
    source = tmp_path / "cookies.txt"
    source.write_bytes(
        newline.join(
            [
                b"# Netscape HTTP Cookie File",
                b".youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsecret",
                b"",
            ]
        )
    )
    report = runtime_report(Settings(_env_file=None, youtube_cookie_file=source))
    assert report["cookie_file_format_valid"] is True
    assert report["cookie_file_newline_style"] == style


def test_diagnostic_manifest_makes_one_attempt_and_classifies_safely():
    result = subprocess.CompletedProcess([], 1, "", "Cookie=secret SSL unexpected EOF")
    with patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result) as run:
        manifest = diagnostic_manifest(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    assert run.call_count == 1
    assert manifest["extractor_attempts"] == 1
    assert manifest["automatic_retries"] == 0
    assert manifest["status"] == "error"
    assert manifest["error"]["code"] == "network_tls"
    assert manifest["log_analysis"]["signals"] == ["network_tls"]
    assert manifest["log_analysis"]["raw_log_included"] is False
    assert "secret" not in json.dumps(manifest)


def test_terminal_error_wins_over_earlier_warning():
    stderr = (
        "WARNING: SSL unexpected EOF while loading an optional page\n"
        "ERROR: Sign in to confirm you are not a bot. Use --cookies"
    )
    result = subprocess.CompletedProcess([], 1, "", stderr)
    with patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result):
        manifest = diagnostic_manifest(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    assert manifest["error"]["code"] == "auth_cookies"
    assert manifest["log_analysis"]["primary"] == "auth_cookies"
    assert manifest["log_analysis"]["signals"] == ["network_tls", "auth_cookies"]
    assert manifest["log_analysis"]["warning_lines"] == 1
    assert manifest["log_analysis"]["error_lines"] == 1


def test_safe_log_facts_classify_read_timeout_without_raw_details():
    stderr = (
        "ERROR: [youtube] secret-id: ReadTimeout token=super-secret-value-1234567890 "
        "while requesting https://example.test/signed?secret=value"
    )
    result = subprocess.CompletedProcess([], 1, "", stderr)
    with patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result):
        manifest = diagnostic_manifest(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    serialized = json.dumps(manifest)
    assert manifest["error"]["code"] == "timeout"
    assert manifest["log_analysis"]["exception_types"] == ["ReadTimeout"]
    assert len(manifest["log_analysis"]["terminal_fingerprint"]) == 12
    assert "super-secret" not in serialized
    assert "example.test" not in serialized


@pytest.mark.parametrize(
    ("stderr", "code", "category", "phase"),
    [
        ("ERROR: HTTP Error 403: Forbidden", "http_forbidden", "remote_policy", "request"),
        (
            "ERROR: Unable to download video data: SSLError unexpected EOF",
            "network_tls",
            "network",
            "tls",
        ),
        (
            "ProxyError: tunnel connection failed",
            "network_connect",
            "network",
            "proxy_or_connection",
        ),
        ("ReadTimeout while reading media", "timeout", "network", "request"),
        (
            "ERROR: unable to download fragment 3",
            "media_delivery",
            "download",
            "media_transfer",
        ),
        (
            "ERROR: requested format is not available",
            "format_unavailable",
            "format",
            "selection",
        ),
        (
            "ERROR: Unable to extract initial player response",
            "extractor_parse",
            "extractor",
            "metadata",
        ),
        (
            "ERROR: cookie file does not look like a Netscape format cookies file",
            "cookie_format",
            "configuration",
            "startup",
        ),
    ],
)
def test_regex_error_taxonomy(stderr, code, category, phase):
    analysis = _analyze_extractor_log(stderr)
    assert analysis["primary"] == code
    assert analysis["category"] == category
    assert analysis["phase"] == phase
    assert analysis["confidence"] in {"high", "medium"}
    assert analysis["stderr_present"] is True


def test_unclassified_stderr_still_has_safe_fingerprint():
    analysis = _analyze_extractor_log("some new upstream failure with token=secret-value")
    assert analysis["primary"] == "extractor"
    assert analysis["category"] == "unknown"
    assert analysis["matched_line_scope"] == "none"
    assert len(analysis["terminal_fingerprint"]) == 12


def test_known_exception_beats_an_unclassified_terminal_wrapper():
    stderr = (
        "WARNING: SSLError during an optional request\n"
        "WARNING: Sign in to confirm you are not a bot\n"
        "ERROR: [youtube] abcdefghijk: operation failed"
    )
    analysis = _analyze_extractor_log(stderr)
    assert analysis["primary"] == "network_tls"
    assert analysis["signals"] == ["network_tls", "auth_cookies"]
    assert analysis["exception_types"] == ["SSLError"]
    assert analysis["matched_line_scope"] == "exception"


def test_warning_signal_beats_an_unclassified_terminal_wrapper_without_exception():
    stderr = (
        "WARNING: Sign in to confirm you are not a bot\n"
        "ERROR: [youtube] abcdefghijk: operation failed"
    )
    analysis = _analyze_extractor_log(stderr)
    assert analysis["primary"] == "auth_cookies"
    assert analysis["matched_line_scope"] == "stderr"


def test_media_error_report_never_includes_raw_log():
    analysis = _analyze_extractor_log(
        "ERROR: ReadTimeout at https://example.test/signed?token=secret-value"
    )
    report = media_error_report(MediaError("Safe timeout", code="timeout", log_analysis=analysis))
    serialized = json.dumps(report)
    assert report["error"]["retry_policy"] == "after_health_check_or_cooldown"
    assert report["log_analysis"]["raw_log_included"] is False
    assert "example.test" not in serialized
    assert "secret-value" not in serialized


def test_diagnostic_contains_unexpected_exception_without_its_message():
    with patch(
        "cats_channel.media.probe",
        side_effect=RuntimeError("secret signed URL and account details"),
    ):
        manifest = diagnostic_manifest(Settings(_env_file=None), "https://youtu.be/abcdefghijk")
    serialized = json.dumps(manifest)
    assert manifest["status"] == "error"
    assert manifest["error"]["code"] == "internal_error"
    assert manifest["error"]["exception_type"] == "RuntimeError"
    assert "secret" not in serialized
    assert "account details" not in serialized


def test_invalid_diagnostic_url_makes_no_extractor_attempt():
    with patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run") as run:
        manifest = diagnostic_manifest(Settings(_env_file=None), "https://example.com/video")
    run.assert_not_called()
    assert manifest["extractor_attempts"] == 0
    assert manifest["error"]["code"] == "invalid_url"


def test_download_uses_one_bounded_extractor_call(tmp_path):
    def fake_run(_settings, args, _timeout, *, socket_timeout):
        match_filter = args[args.index("--match-filter") + 1]
        assert "duration > 0" in match_filter
        assert "duration <= 300" in match_filter
        assert "live_status = not_live" in match_filter
        assert socket_timeout == 45
        (tmp_path / "video.mp4").write_bytes(b"video")
        return ""

    with patch("cats_channel.media._run", side_effect=fake_run) as run:
        download(Settings(_env_file=None), "https://youtu.be/abcdefghijk", tmp_path)
    assert run.call_count == 1


def test_download_can_capture_safe_metadata_in_same_extractor_call(tmp_path):
    raw_metadata = {
        "id": "abcdefghijk",
        "title": "Cat",
        "duration": 10,
        "channel": "Cats",
        "url": "https://signed-private-url",
        "http_headers": {"Cookie": "secret"},
    }

    def fake_run(_settings, args, _timeout, *, socket_timeout):
        assert "--no-simulate" in args
        assert "--print-json" in args
        assert socket_timeout == 45
        (tmp_path / "video.mp4").write_bytes(b"video")
        return json.dumps(raw_metadata)

    metadata = {}
    with patch("cats_channel.media._run", side_effect=fake_run) as run:
        path = download(
            Settings(_env_file=None),
            "https://youtu.be/abcdefghijk",
            tmp_path,
            metadata_out=metadata,
        )
    assert run.call_count == 1
    assert path.name == "video.mp4"
    assert metadata["title"] == "Cat"
    assert metadata["channel"] == "Cats"
    assert "url" not in metadata
    assert "http_headers" not in metadata


def test_post_download_size_check(tmp_path):
    settings = Settings(_env_file=None, max_download_mb=1)
    (tmp_path / "video.mp4").write_bytes(b"x" * (1024 * 1024 + 1))
    with (
        patch("cats_channel.media._run", return_value=""),
        pytest.raises(MediaError, match="upload limit"),
    ):
        download(settings, "https://youtu.be/abcdefghijk", tmp_path)


@pytest.mark.parametrize(
    ("ffmpeg", "expected_fragment"),
    [
        ("/usr/bin/ffmpeg", "bestaudio[ext=m4a]"),
        (None, "best[height<=720][ext=mp4]"),
    ],
)
def test_download_selects_practical_format_for_runtime(tmp_path, ffmpeg, expected_fragment):
    def fake_run(_settings, args, _timeout, *, socket_timeout):
        (tmp_path / "video.mp4").write_bytes(b"video")
        assert expected_fragment in args[args.index("-f") + 1]
        assert ("--merge-output-format" in args) is bool(ffmpeg)
        assert socket_timeout == 45
        return ""

    with (
        patch("cats_channel.media.shutil.which", return_value=ffmpeg),
        patch("cats_channel.media._run", side_effect=fake_run),
    ):
        assert (
            download(Settings(_env_file=None), "https://youtu.be/abcdefghijk", tmp_path).name
            == "video.mp4"
        )


def test_explicit_proxy_is_passed_to_yt_dlp_without_direct_fallback():
    metadata = json.dumps({"id": "abcdefghijk", "title": "Cat", "duration": 10})
    result = subprocess.CompletedProcess([], 0, metadata, "")
    settings = Settings(_env_file=None, youtube_proxy="socks5h://127.0.0.1:10808")
    with patch("cats_channel.media.DEFAULT_PROCESS_RUNNER.run", return_value=result) as run:
        probe(settings, "https://youtu.be/abcdefghijk")
    command = run.call_args.args[0]
    assert command[command.index("--proxy") + 1].rstrip("/") == ("socks5h://127.0.0.1:10808")


def test_settings_hide_token_and_require_admin():
    settings = Settings(_env_file=None, bot_token="123:secret", admin_user_id=None)
    assert "123:secret" not in repr(settings)
    with pytest.raises(MediaError) as error:
        settings.require_bot()
    assert error.value.code == "invalid_config"
    assert "123:secret" not in str(error.value)
