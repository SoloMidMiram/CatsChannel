import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import MediaError

VIDEO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MediaError(f"Downloader metadata field {field} is invalid.", code="metadata_invalid")
    return value


def _optional_number(value: object, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MediaError(f"Downloader metadata field {field} is invalid.", code="metadata_invalid")
    if not math.isfinite(float(value)):
        raise MediaError(f"Downloader metadata field {field} is invalid.", code="metadata_invalid")
    return value


@dataclass(frozen=True)
class VideoMetadata:
    id: str
    title: str
    duration: int | float
    availability: str | None = None
    live_status: str | None = None
    webpage_url: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    uploader: str | None = None
    uploader_id: str | None = None
    upload_date: str | None = None
    timestamp: int | float | None = None
    width: int | float | None = None
    height: int | float | None = None
    fps: int | float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    format_id: str | None = None
    format_note: str | None = None
    ext: str | None = None

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        expected_id: str | None = None,
        max_duration: int | None = None,
    ) -> "VideoMetadata":
        if not isinstance(value, dict):
            raise MediaError("Downloader returned invalid metadata.", code="metadata_invalid")
        video_id = value.get("id")
        title = value.get("title")
        duration = _optional_number(value.get("duration"), "duration")
        if not isinstance(video_id, str) or not VIDEO_ID_PATTERN.fullmatch(video_id):
            raise MediaError("Downloader returned an invalid video ID.", code="metadata_invalid")
        if expected_id is not None and video_id != expected_id:
            raise MediaError(
                "Downloaded metadata does not match the requested video.", code="metadata_invalid"
            )
        if not isinstance(title, str) or not title.strip():
            raise MediaError("Downloader returned an invalid title.", code="metadata_invalid")
        if duration is None or float(duration) <= 0:
            raise MediaError("Downloader returned an invalid duration.", code="metadata_invalid")
        if max_duration is not None and float(duration) > max_duration:
            raise MediaError(
                "The video exceeds the configured duration limit.", code="policy_limit"
            )
        return cls(
            id=video_id,
            title=title,
            duration=duration,
            availability=_optional_string(value.get("availability"), "availability"),
            live_status=_optional_string(value.get("live_status"), "live_status"),
            webpage_url=_optional_string(value.get("webpage_url"), "webpage_url"),
            channel=_optional_string(value.get("channel"), "channel"),
            channel_id=_optional_string(value.get("channel_id"), "channel_id"),
            uploader=_optional_string(value.get("uploader"), "uploader"),
            uploader_id=_optional_string(value.get("uploader_id"), "uploader_id"),
            upload_date=_optional_string(value.get("upload_date"), "upload_date"),
            timestamp=_optional_number(value.get("timestamp"), "timestamp"),
            width=_optional_number(value.get("width"), "width"),
            height=_optional_number(value.get("height"), "height"),
            fps=_optional_number(value.get("fps"), "fps"),
            vcodec=_optional_string(value.get("vcodec"), "vcodec"),
            acodec=_optional_string(value.get("acodec"), "acodec"),
            format_id=_optional_string(value.get("format_id"), "format_id"),
            format_note=_optional_string(value.get("format_note"), "format_note"),
            ext=_optional_string(value.get("ext"), "ext"),
        )

    def to_dict(self, *, compact: bool = False) -> dict[str, Any]:
        value = asdict(self)
        if compact:
            keys = ("id", "title", "duration", "availability", "live_status", "webpage_url")
            return {key: value[key] for key in keys}
        return value


@dataclass(frozen=True)
class DownloadArtifact:
    path: Path
    metadata: VideoMetadata


@dataclass(frozen=True)
class LibraryItem:
    status: str
    item_path: str
    media_path: Path
    manifest: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "item_path": self.item_path,
            "manifest": self.manifest,
        }
