import json
import subprocess
import threading
import time
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from cats_channel import library as media_library
from cats_channel.config import Settings
from cats_channel.library import _probe_media, list_downloads, store_download, verify_download
from cats_channel.media import MediaError

VIDEO_ID = "abcdefghijk"
VIDEO_URL = f"https://youtu.be/{VIDEO_ID}"
PLAYBACK = {
    "status": "passed",
    "full_decode": "passed",
    "duration_seconds": 12.0,
    "format_name": "mov,mp4",
    "video_stream_count": 1,
    "audio_stream_count": 1,
    "video_codec": "h264",
    "width": 720,
    "height": 1280,
    "audio_codecs": ["aac"],
}


def _fake_download(_settings, _url, directory: Path, *, metadata_out):
    path = directory / "video.mp4"
    path.write_bytes(b"cat-video")
    metadata_out.update(
        {
            "id": VIDEO_ID,
            "title": "A cat",
            "duration": 12,
            "availability": "public",
            "live_status": "not_live",
            "webpage_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        }
    )
    return path


def test_store_download_creates_self_contained_item_and_reuses_it(tmp_path):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    with (
        patch("cats_channel.library.download", side_effect=_fake_download) as downloader,
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        result = store_download(settings, VIDEO_URL)
        existing = store_download(settings, VIDEO_URL)

    item = tmp_path / "library" / "youtube" / VIDEO_ID
    media = item / "media.mp4"
    manifest = json.loads((item / "manifest.json").read_text(encoding="utf-8"))
    assert downloader.call_count == 1
    assert result["status"] == "stored"
    assert existing["status"] == "existing"
    assert media.read_bytes() == b"cat-video"
    assert manifest["source"]["video_id"] == VIDEO_ID
    assert manifest["metadata"]["title"] == "A cat"
    assert manifest["playback_validation"] == PLAYBACK
    assert manifest["file"]["size_bytes"] == len(b"cat-video")
    assert manifest["file"]["sha256"] == sha256(b"cat-video").hexdigest()
    assert list((tmp_path / ".staging").iterdir()) == []


def test_list_and_verify_downloads_are_local(tmp_path):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    with (
        patch("cats_channel.library.download", side_effect=_fake_download),
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        store_download(settings, VIDEO_URL)
        records = list_downloads(settings)
        verification = verify_download(settings, VIDEO_ID)
    assert records == [
        {
            "status": "stored",
            "video_id": VIDEO_ID,
            "title": "A cat",
            "duration": 12,
            "downloaded_at": records[0]["downloaded_at"],
            "file_name": "media.mp4",
            "size_bytes": len(b"cat-video"),
            "item_path": f"library/youtube/{VIDEO_ID}",
        }
    ]
    assert verification["status"] == "ok"
    assert verification["source_matches"] is True
    assert verification["size_matches"] is True
    assert verification["sha256_matches"] is True
    assert verification["playback_validation"] == PLAYBACK


def test_verify_detects_changed_media(tmp_path):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    with (
        patch("cats_channel.library.download", side_effect=_fake_download),
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        store_download(settings, VIDEO_URL)
    (tmp_path / "library" / "youtube" / VIDEO_ID / "media.mp4").write_bytes(b"changed")

    with patch("cats_channel.library._probe_media", return_value=PLAYBACK):
        result = verify_download(settings, VIDEO_ID)
    assert result["status"] == "corrupt"
    assert result["sha256_matches"] is False


def test_verify_detects_mismatched_source_video_id(tmp_path):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    with (
        patch("cats_channel.library.download", side_effect=_fake_download),
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        store_download(settings, VIDEO_URL)

    manifest_path = tmp_path / "library" / "youtube" / VIDEO_ID / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source"]["video_id"] = "zyxwvutsrqp"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with patch("cats_channel.library._probe_media", return_value=PLAYBACK):
        result = verify_download(settings, VIDEO_ID)

    assert result["status"] == "corrupt"
    assert result["source_matches"] is False
    assert result["size_matches"] is True
    assert result["sha256_matches"] is True


def test_verify_enforces_current_size_limit(tmp_path):
    def large_download(_settings, _url, directory: Path, *, metadata_out):
        path = directory / "video.mp4"
        path.write_bytes(b"x" * (2 * 1024 * 1024))
        metadata_out.update(
            {
                "id": VIDEO_ID,
                "title": "A large cat",
                "duration": 12,
                "availability": "public",
                "live_status": "not_live",
                "webpage_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
            }
        )
        return path

    initial = Settings(_env_file=None, download_dir=tmp_path, max_download_mb=45)
    restrictive = Settings(_env_file=None, download_dir=tmp_path, max_download_mb=1)
    with (
        patch("cats_channel.library.download", side_effect=large_download),
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        store_download(initial, VIDEO_URL)
        with pytest.raises(MediaError) as error:
            verify_download(restrictive, VIDEO_ID)

    assert error.value.code == "policy_limit"


def test_corrupt_cache_is_not_returned_or_redownloaded(tmp_path):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    with (
        patch("cats_channel.library.download", side_effect=_fake_download) as downloader,
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        store_download(settings, VIDEO_URL)
        (tmp_path / "library" / "youtube" / VIDEO_ID / "media.mp4").write_bytes(b"changed")
        with pytest.raises(MediaError) as error:
            store_download(settings, VIDEO_URL)
    assert error.value.code == "cache_corrupt"
    assert downloader.call_count == 1


def test_cache_hit_enforces_current_duration_limit(tmp_path):
    initial = Settings(_env_file=None, download_dir=tmp_path, max_duration_seconds=300)
    restrictive = Settings(_env_file=None, download_dir=tmp_path, max_duration_seconds=1)
    with (
        patch("cats_channel.library.download", side_effect=_fake_download) as downloader,
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        store_download(initial, VIDEO_URL)
        with pytest.raises(MediaError) as error:
            store_download(restrictive, VIDEO_URL)

    assert error.value.code == "policy_limit"
    assert downloader.call_count == 1


def test_cache_hit_enforces_current_size_limit(tmp_path):
    def large_download(_settings, _url, directory: Path, *, metadata_out):
        path = directory / "video.mp4"
        path.write_bytes(b"x" * (2 * 1024 * 1024))
        metadata_out.update(
            {
                "id": VIDEO_ID,
                "title": "A large cat",
                "duration": 12,
                "availability": "public",
                "live_status": "not_live",
                "webpage_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
            }
        )
        return path

    initial = Settings(_env_file=None, download_dir=tmp_path, max_download_mb=45)
    restrictive = Settings(_env_file=None, download_dir=tmp_path, max_download_mb=1)
    with (
        patch("cats_channel.library.download", side_effect=large_download) as downloader,
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        store_download(initial, VIDEO_URL)
        with pytest.raises(MediaError) as error:
            store_download(restrictive, VIDEO_URL)

    assert error.value.code == "policy_limit"
    assert downloader.call_count == 1


def test_failed_validation_leaves_no_published_or_staged_item(tmp_path):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    with (
        patch("cats_channel.library.download", side_effect=_fake_download),
        patch(
            "cats_channel.library._probe_media",
            side_effect=MediaError(code="media_validation"),
        ),
        pytest.raises(MediaError) as error,
    ):
        store_download(settings, VIDEO_URL)
    assert error.value.code == "media_validation"
    assert not (tmp_path / "library" / "youtube" / VIDEO_ID).exists()
    assert list((tmp_path / ".staging").iterdir()) == []


@pytest.mark.parametrize(
    ("primary_error", "expected_code"),
    [
        (OSError("private path"), "local_io"),
        (KeyboardInterrupt(), "cancelled"),
        (RuntimeError("private implementation detail"), "internal_error"),
    ],
)
def test_cleanup_warning_preserves_non_media_error_classification(
    tmp_path, primary_error, expected_code
):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    with (
        patch("cats_channel.library.download", side_effect=primary_error),
        patch("cats_channel.library.shutil.rmtree", side_effect=OSError("cleanup failed")),
        pytest.raises(MediaError) as error,
    ):
        store_download(settings, VIDEO_URL)

    assert error.value.code == expected_code
    assert error.value.warnings == ("staging_cleanup_failed",)
    assert error.value.__cause__ is primary_error
    assert "private" not in str(error.value)


def test_concurrent_acquisition_downloads_once_and_reuses_verified_item(tmp_path):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    barrier = threading.Barrier(2)
    results = []

    def slow_download(*args, **kwargs):
        time.sleep(0.1)
        return _fake_download(*args, **kwargs)

    def acquire():
        barrier.wait()
        results.append(store_download(settings, VIDEO_URL)["status"])

    with (
        patch("cats_channel.library.download", side_effect=slow_download) as downloader,
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        threads = [threading.Thread(target=acquire) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(results) == ["existing", "stored"]
    assert downloader.call_count == 1


def test_library_root_exists_before_the_per_video_lock_key_is_resolved(tmp_path):
    settings = Settings(_env_file=None, download_dir=tmp_path)
    original_item_lock = media_library._item_lock

    def checked_item_lock(root, video_id):
        assert root.is_dir()
        return original_item_lock(root, video_id)

    with (
        patch("cats_channel.library._item_lock", side_effect=checked_item_lock),
        patch("cats_channel.library.download", side_effect=_fake_download),
        patch("cats_channel.library._probe_media", return_value=PLAYBACK),
    ):
        result = store_download(settings, VIDEO_URL)

    assert result["status"] == "stored"


def test_ffprobe_validation_records_playable_streams(tmp_path):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"video")
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "12.1", "format_name": "mov,mp4"},
    }
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    decode = subprocess.CompletedProcess([], 0, b"", b"")
    with (
        patch("cats_channel.adapters.validation.shutil.which", return_value="/usr/bin/ffprobe"),
        patch(
            "cats_channel.adapters.validation.DEFAULT_PROCESS_RUNNER.run",
            side_effect=[result, decode],
        ),
    ):
        validation = _probe_media(media, 12)
    assert validation["status"] == "passed"
    assert validation["full_decode"] == "passed"
    assert validation["duration_seconds"] == 12.1
    assert validation["video_codec"] == "h264"
    assert validation["audio_codecs"] == ["aac"]


def test_ffprobe_rejects_implausible_duration(tmp_path):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"video")
    payload = {
        "streams": [{"codec_type": "video", "codec_name": "h264"}],
        "format": {"duration": "2", "format_name": "mov,mp4"},
    }
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    with (
        patch("cats_channel.adapters.validation.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("cats_channel.adapters.validation.DEFAULT_PROCESS_RUNNER.run", return_value=result),
        pytest.raises(MediaError) as error,
    ):
        _probe_media(media, 12)
    assert error.value.code == "media_validation"


@pytest.mark.parametrize("duration", ["nan", "NaN", "inf", "-inf"])
def test_ffprobe_rejects_non_finite_duration(tmp_path, duration):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"video")
    payload = {
        "streams": [{"codec_type": "video", "codec_name": "h264"}],
        "format": {"duration": duration, "format_name": "mov,mp4"},
    }
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    with (
        patch("cats_channel.adapters.validation.shutil.which", return_value="ffprobe"),
        patch("cats_channel.adapters.validation.DEFAULT_PROCESS_RUNNER.run", return_value=result),
        pytest.raises(MediaError) as error,
    ):
        _probe_media(media, 12)
    assert error.value.code == "media_validation"
