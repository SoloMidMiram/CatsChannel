import errno
import json
import math
import re
import shutil
import tempfile
import threading
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

from .adapters.process import CancellationToken
from .adapters.validation import validate_media
from .config import Settings
from .errors import MediaError, cleanup_warning_error
from .media import download, youtube_url

MANIFEST_NAME = "manifest.json"
LIBRARY_SCHEMA_VERSION = 2
_LOCKS_GUARD = threading.Lock()
_VIDEO_LOCKS: dict[tuple[str, str], threading.Lock] = {}


def _video_id(url: str) -> tuple[str, str]:
    canonical = youtube_url(url)
    return canonical, parse_qs(urlsplit(canonical).query)["v"][0]


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _library_root(settings: Settings) -> Path:
    return settings.download_dir / "library" / "youtube"


def _relative_item_path(video_id: str) -> str:
    return str(PurePosixPath("library") / "youtube" / video_id)


def _read_manifest(folder: Path) -> dict[str, object]:
    try:
        manifest = json.loads(
            (folder / MANIFEST_NAME).read_text(encoding="utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, ValueError, TypeError):
        raise MediaError(
            "Stored download manifest is missing or invalid.", code="local_io"
        ) from None
    if not isinstance(manifest, dict) or manifest.get("schema_version") != LIBRARY_SCHEMA_VERSION:
        raise MediaError("Stored download manifest has an unsupported schema.", code="local_io")
    if not isinstance(manifest.get("source"), dict) or not isinstance(
        manifest.get("metadata"), dict
    ):
        raise MediaError("Stored download manifest has invalid metadata.", code="local_io")
    playback = manifest.get("playback_validation")
    if not isinstance(playback, dict) or playback.get("status") != "passed":
        raise MediaError("Stored download has no valid playback record.", code="local_io")
    file_record = manifest.get("file")
    if not isinstance(file_record, dict) or not isinstance(file_record.get("name"), str):
        raise MediaError("Stored download manifest has no valid media file.", code="local_io")
    media_path = folder / file_record["name"]
    if media_path.parent != folder or not media_path.is_file():
        raise MediaError("Stored media file is missing.", code="local_io")
    return manifest


def _item_lock(root: Path, video_id: str) -> threading.Lock:
    key = (str(root.resolve()), video_id)
    with _LOCKS_GUARD:
        return _VIDEO_LOCKS.setdefault(key, threading.Lock())


def _verified_existing(folder: Path, video_id: str) -> dict[str, object]:
    manifest = _read_manifest(folder)
    source = manifest["source"]
    file_record = manifest["file"]
    if source.get("video_id") != video_id:
        raise MediaError("Stored media source does not match its directory.", code="cache_corrupt")
    expected_size = file_record.get("size_bytes")
    expected_hash = file_record.get("sha256")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size <= 0
        or not isinstance(expected_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
    ):
        raise MediaError("Stored media integrity record is invalid.", code="cache_corrupt")
    media_path = folder / str(file_record["name"])
    try:
        actual_size = media_path.stat().st_size
        actual_hash = _hash_file(media_path)
    except OSError:
        raise MediaError("Stored media could not be verified.", code="cache_corrupt") from None
    if actual_size != expected_size or actual_hash != expected_hash:
        raise MediaError("Stored media does not match its manifest.", code="cache_corrupt")
    return manifest


def _enforce_current_policy(manifest: dict[str, object], settings: Settings) -> None:
    file_record = manifest["file"]
    playback = manifest["playback_validation"]
    size_bytes = file_record.get("size_bytes")
    duration = playback.get("duration_seconds")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise MediaError("Stored media policy data is invalid.", code="cache_corrupt")
    if size_bytes > settings.max_download_mb * 1024 * 1024:
        raise MediaError("Stored media exceeds the current size limit.", code="policy_limit")
    if duration > settings.max_duration_seconds:
        raise MediaError("Stored media exceeds the current duration limit.", code="policy_limit")


def _cleanup_warning_error(primary_error: BaseException) -> MediaError:
    return cleanup_warning_error(primary_error, "staging_cleanup_failed")


def _yt_dlp_version() -> str | None:
    try:
        return version("yt-dlp")
    except PackageNotFoundError:
        return None


def _probe_media(
    path: Path,
    expected_duration: object,
    *,
    max_duration_seconds: int | None = None,
    token: CancellationToken | None = None,
) -> dict[str, object]:
    """Require stream inspection and a full decode before persistent publication."""
    return validate_media(
        path,
        expected_duration,
        max_duration_seconds=max_duration_seconds,
        token=token,
    )


def store_download(
    settings: Settings,
    url: str,
    *,
    token: CancellationToken | None = None,
) -> dict[str, object]:
    """Download once into a self-contained, atomically published library item."""
    canonical, video_id = _video_id(url)
    root = _library_root(settings)
    destination = root / video_id
    with _item_lock(root, video_id):
        if destination.exists():
            manifest = _verified_existing(destination, video_id)
            _enforce_current_policy(manifest, settings)
            return {
                "status": "existing",
                "item_path": _relative_item_path(video_id),
                "manifest": manifest,
            }

        staging_root = settings.download_dir / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f"{video_id}-", dir=staging_root))
        metadata: dict[str, object] = {}
        primary_error: BaseException | None = None
        try:
            download_kwargs: dict[str, object] = {"metadata_out": metadata}
            if token is not None:
                download_kwargs["token"] = token
            if settings.media_backend == "telegram_bot":
                from .adapters.telegram_downloader import download_video

                downloaded = download_video(settings, canonical, staging, **download_kwargs)
            else:
                downloaded = download(settings, canonical, staging, **download_kwargs)
            if metadata.get("id") != video_id:
                raise MediaError(
                    "Downloaded metadata does not match the requested video.",
                    code="metadata_invalid",
                )
            media_path = staging / f"media{downloaded.suffix.lower()}"
            downloaded.rename(media_path)
            playback_validation = _probe_media(
                media_path,
                metadata.get("duration"),
                max_duration_seconds=settings.max_duration_seconds,
                token=token,
            )
            receipt = metadata.pop("_telegram_receipt", None)
            if settings.media_backend == "telegram_bot":
                metadata["duration"] = playback_validation["duration_seconds"]
                metadata["width"] = playback_validation.get("width")
                metadata["height"] = playback_validation.get("height")
                metadata["vcodec"] = playback_validation.get("video_codec")
            manifest: dict[str, object] = {
                "schema_version": LIBRARY_SCHEMA_VERSION,
                "downloaded_at": datetime.now(UTC).isoformat(),
                "source": {
                    "provider": "youtube",
                    "video_id": video_id,
                    "canonical_url": canonical,
                },
                "metadata": metadata,
                "playback_validation": playback_validation,
                "file": {
                    "name": media_path.name,
                    "size_bytes": media_path.stat().st_size,
                    "sha256": _hash_file(media_path),
                },
                "download_policy": {
                    "max_download_mb": settings.max_download_mb,
                    "max_duration_seconds": settings.max_duration_seconds,
                    "yt_dlp_version": (
                        _yt_dlp_version() if settings.media_backend == "yt_dlp" else None
                    ),
                },
                "acquisition": {"backend": settings.media_backend, "receipt": receipt},
            }
            try:
                serialized = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)
            except (TypeError, ValueError):
                raise MediaError(
                    "Media manifest contains invalid values.", code="metadata_invalid"
                ) from None
            (staging / MANIFEST_NAME).write_text(serialized + "\n", encoding="utf-8")
            try:
                staging.rename(destination)
            except OSError as error:
                if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                existing = _verified_existing(destination, video_id)
                _enforce_current_policy(existing, settings)
                return {
                    "status": "existing",
                    "item_path": _relative_item_path(video_id),
                    "manifest": existing,
                }
            return {
                "status": "stored",
                "item_path": _relative_item_path(video_id),
                "manifest": manifest,
            }
        except BaseException as error:
            primary_error = error
            raise
        finally:
            if staging.exists():
                try:
                    shutil.rmtree(staging)
                except OSError:
                    if isinstance(primary_error, MediaError):
                        primary_error.warnings += ("staging_cleanup_failed",)
                    elif primary_error is not None:
                        raise _cleanup_warning_error(primary_error) from primary_error
                    elif primary_error is None:
                        raise MediaError(code="cleanup_failed") from None


def list_downloads(settings: Settings) -> list[dict[str, object]]:
    """Return compact records; corrupt entries are visible instead of silently skipped."""
    root = _library_root(settings)
    if not root.is_dir():
        return []
    records: list[dict[str, object]] = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            manifest = _verified_existing(folder, folder.name)
            source = manifest.get("source", {})
            metadata = manifest.get("metadata", {})
            file_record = manifest.get("file", {})
            records.append(
                {
                    "status": "stored",
                    "video_id": source.get("video_id"),
                    "title": metadata.get("title"),
                    "duration": metadata.get("duration"),
                    "downloaded_at": manifest.get("downloaded_at"),
                    "file_name": file_record.get("name"),
                    "size_bytes": file_record.get("size_bytes"),
                    "item_path": _relative_item_path(folder.name),
                }
            )
        except MediaError as error:
            records.append(
                {
                    "status": "invalid",
                    "video_id": folder.name,
                    "error": str(error),
                    "item_path": _relative_item_path(folder.name),
                }
            )
    return records


def verify_download(settings: Settings, video_id: str) -> dict[str, object]:
    """Check a local item against its manifest without making a network request."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Expected an 11-character YouTube video ID.")
    folder = _library_root(settings) / video_id
    manifest = _read_manifest(folder)
    file_record = manifest["file"]
    media_path = folder / str(file_record["name"])
    actual_size = media_path.stat().st_size
    actual_hash = _hash_file(media_path)
    playback_validation = _probe_media(
        media_path,
        manifest["metadata"].get("duration"),
        max_duration_seconds=settings.max_duration_seconds,
    )
    source_matches = manifest["source"].get("video_id") == video_id
    size_matches = actual_size == file_record.get("size_bytes")
    hash_matches = actual_hash == file_record.get("sha256")
    is_intact = source_matches and size_matches and hash_matches
    if is_intact:
        _enforce_current_policy(manifest, settings)
    return {
        "status": "ok" if is_intact else "corrupt",
        "video_id": video_id,
        "item_path": _relative_item_path(video_id),
        "size_bytes": actual_size,
        "source_matches": source_matches,
        "size_matches": size_matches,
        "sha256_matches": hash_matches,
        "playback_validation": playback_validation,
    }
