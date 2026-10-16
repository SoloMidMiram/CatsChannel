import json
import math
import shutil
from pathlib import Path

from ..errors import MediaError
from .process import DEFAULT_PROCESS_RUNNER, CancellationToken, OwnedProcessRunner


def validate_media(
    path: Path,
    expected_duration: object,
    *,
    max_duration_seconds: int | None = None,
    token: CancellationToken | None = None,
    runner: OwnedProcessRunner = DEFAULT_PROCESS_RUNNER,
) -> dict[str, object]:
    """Require finite metadata, a video stream, and a complete decode."""
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if ffprobe is None or ffmpeg is None:
        raise MediaError(
            "FFmpeg and FFprobe are required to validate persistent library downloads.",
            code="media_validation",
        )
    result = runner.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        timeout=30,
        token=token,
    )
    if result.returncode:
        raise MediaError("The downloaded file is not a readable video.", code="media_validation")
    try:
        payload = json.loads(
            result.stdout, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError())
        )
        streams = payload["streams"]
        format_info = payload["format"]
        duration = float(format_info["duration"])
    except (KeyError, TypeError, ValueError):
        raise MediaError(
            "FFprobe returned invalid media metadata.", code="media_validation"
        ) from None
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("The downloaded file has an invalid duration.", code="media_validation")
    if max_duration_seconds is not None and duration > max_duration_seconds:
        raise MediaError("The downloaded file exceeds the duration policy.", code="policy_limit")
    if not isinstance(streams, list) or not all(isinstance(stream, dict) for stream in streams):
        raise MediaError("FFprobe returned invalid media metadata.", code="media_validation")
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if not video_streams:
        raise MediaError("The downloaded file is not a readable video.", code="media_validation")
    first_video = video_streams[0]
    width = first_video.get("width")
    height = first_video.get("height")
    if width is not None and (not isinstance(width, int) or width <= 0):
        raise MediaError("FFprobe returned invalid video dimensions.", code="media_validation")
    if height is not None and (not isinstance(height, int) or height <= 0):
        raise MediaError("FFprobe returned invalid video dimensions.", code="media_validation")
    if isinstance(expected_duration, bool):
        raise MediaError("Expected media duration is invalid.", code="media_validation")
    if isinstance(expected_duration, (int, float)):
        expected = float(expected_duration)
        if not math.isfinite(expected) or expected <= 0:
            raise MediaError("Expected media duration is invalid.", code="media_validation")
        tolerance = max(3.0, expected * 0.05)
        if abs(duration - expected) > tolerance:
            raise MediaError(
                "The downloaded media duration does not match its metadata.",
                code="media_validation",
            )
    decode = runner.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ],
        timeout=300,
        token=token,
        text=False,
    )
    if decode.returncode:
        raise MediaError(
            "The downloaded file failed full decode validation.", code="media_validation"
        )
    return {
        "status": "passed",
        "full_decode": "passed",
        "duration_seconds": round(duration, 3),
        "format_name": format_info.get("format_name"),
        "video_stream_count": len(video_streams),
        "audio_stream_count": len(audio_streams),
        "video_codec": first_video.get("codec_name"),
        "width": width,
        "height": height,
        "audio_codecs": sorted(
            {stream["codec_name"] for stream in audio_streams if stream.get("codec_name")}
        ),
    }
