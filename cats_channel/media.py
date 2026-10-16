import json
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .adapters.cookies import cookie_health, working_cookie_file
from .adapters.process import DEFAULT_PROCESS_RUNNER, CancellationToken
from .config import Settings
from .errors import ERROR_POLICIES, MediaError, error_record
from .errors import media_error_report as _media_error_report
from .models import DownloadArtifact, VideoMetadata


def youtube_url(value: str) -> str:
    """Accept individual YouTube videos only; never arbitrary downloader URLs."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ValueError("Use an HTTPS YouTube video link without credentials or a port.")
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.removeprefix("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/")):
            video_id = parsed.path.split("/")[-1]
        else:
            video_id = ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Expected one youtube.com/watch, /shorts, /live or youtu.be video.")
    return f"https://www.youtube.com/watch?v={video_id}"


def _cookie_health(path: Path) -> dict[str, object]:
    return cookie_health(path)


def runtime_report(settings: Settings) -> dict[str, object]:
    """Return safe local diagnostics without exposing paths or secret values."""
    try:
        yt_dlp_version = version("yt-dlp")
    except PackageNotFoundError:
        yt_dlp_version = None
    try:
        pot_plugin_version = version("bgutil-ytdlp-pot-provider")
    except PackageNotFoundError:
        pot_plugin_version = None
    cookie_exists: bool | None = None
    cookie_check_error = False
    cookie_health: dict[str, object] = {
        "cookie_file_readable": None,
        "cookie_file_format_valid": None,
        "cookie_file_newline_style": None,
        "cookie_file_entries": None,
        "cookie_file_youtube_entries": None,
        "cookie_file_expired_entries": None,
        "cookie_file_session_entries": None,
    }
    if settings.youtube_cookie_file is not None:
        try:
            cookie_exists = settings.youtube_cookie_file.is_file()
            if cookie_exists:
                cookie_health.update(_cookie_health(settings.youtube_cookie_file))
        except OSError:
            cookie_exists = False
            cookie_check_error = True
    return {
        "python": sys.version.split()[0],
        "yt_dlp": yt_dlp_version,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "deno": shutil.which("deno") is not None,
        "node": shutil.which("node") is not None,
        "youtube_profile": settings.youtube_profile,
        "youtube_proxy_configured": settings.youtube_proxy is not None,
        "youtube_proxy_scheme": settings.youtube_proxy.scheme if settings.youtube_proxy else None,
        "pot_plugin_version": pot_plugin_version,
        "pot_provider_configured": settings.youtube_pot_provider_url is not None,
        "pot_profile_ready": (
            settings.youtube_profile == "pot_bgutil"
            and pot_plugin_version is not None
            and settings.youtube_pot_provider_url is not None
        ),
        "youtube_profile_ready": settings.youtube_profile == "baseline"
        or (pot_plugin_version is not None and settings.youtube_pot_provider_url is not None),
        "cookie_file_configured": settings.youtube_cookie_file is not None,
        "cookie_file_exists": cookie_exists,
        "cookie_file_check_error": cookie_check_error,
        **cookie_health,
        "cookie_handling": (
            "disposable_copy" if settings.youtube_cookie_file is not None else "none"
        ),
    }


_ERROR_MESSAGES = {code: policy.message for code, policy in ERROR_POLICIES.items()}


@dataclass(frozen=True)
class _ErrorRule:
    code: str
    category: str
    phase: str
    confidence: str
    patterns: tuple[re.Pattern[str], ...]


def _rule(
    code: str,
    category: str,
    phase: str,
    confidence: str,
    *patterns: str,
) -> _ErrorRule:
    return _ErrorRule(
        code,
        category,
        phase,
        confidence,
        tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns),
    )


# Specific rules precede generic transport/parser rules. Keep codes stable because
# operators and tests use them as the public diagnostic contract.
_ERROR_RULES = (
    _rule(
        "video_unavailable",
        "content",
        "metadata",
        "high",
        r"\bvideo unavailable\b",
        r"\bprivate video\b",
        r"video (?:has been|was) removed",
        r"account associated with this video has been terminated",
    ),
    _rule(
        "auth_cookies",
        "authentication",
        "metadata",
        "high",
        r"sign in to confirm",
        r"\blogin required\b",
        r"use --cookies(?:-from-browser)?",
        r"members.?only content",
        r"authentication required",
        r"cookies?.*(?:expired|no longer valid)",
    ),
    _rule(
        "cookie_format",
        "configuration",
        "startup",
        "high",
        r"does not look like a netscape format cookies file",
        r"invalid netscape.*cookie",
        r"cookie file.*(?:invalid|malformed)",
    ),
    _rule(
        "geo_restricted",
        "content",
        "metadata",
        "high",
        r"not available in your country",
        r"geo.?restricted",
        r"geographic restriction",
    ),
    _rule(
        "pot_provider",
        "attestation",
        "provider",
        "high",
        r"error fetching po[ _-]?token",
        r"error reaching post /get_pot",
        r"po[ _-]?token provider.*(?:unavailable|failed)",
        r"no .*po[ _-]?token providers",
    ),
    _rule("po_token", "attestation", "format", "high", r"po[ _-]?token", r"proof of origin"),
    _rule(
        "policy_limit",
        "policy",
        "filter",
        "high",
        r"does not pass filter",
        r"did not pass filter",
    ),
    _rule(
        "rate_limit",
        "remote_policy",
        "request",
        "high",
        r"http error 429",
        r"too many requests",
        r"rate.?limit",
    ),
    _rule(
        "http_forbidden",
        "remote_policy",
        "request",
        "high",
        r"http error 403",
        r"\b403 forbidden\b",
    ),
    _rule(
        "proxy_upstream",
        "network",
        "proxy",
        "high",
        r"http error 50[0234]",
        r"bad gateway",
        r"service unavailable",
        r"gateway timeout",
    ),
    _rule(
        "js_runtime",
        "runtime",
        "challenge",
        "high",
        r"javascript runtime",
        r"\bjs runtime\b",
        r"challenge solver",
        r"n challenge",
    ),
    _rule("ffmpeg", "runtime", "postprocess", "high", r"\bffmpeg\b"),
    _rule(
        "format_unavailable",
        "format",
        "selection",
        "high",
        r"requested format is not available",
        r"no video formats found",
        r"only images are available",
    ),
    _rule(
        "media_delivery",
        "download",
        "media_transfer",
        "medium",
        r"unable to download (?:video )?data",
        r"unable to download fragment",
        r"fragment \d+ not found",
        r"giving up after \d+ fragment retries",
    ),
    _rule(
        "local_io",
        "local",
        "filesystem",
        "high",
        r"no space left on device",
        r"read-only file system",
        r"permission denied",
    ),
    _rule(
        "network_tls",
        "network",
        "tls",
        "high",
        r"unexpected eof",
        r"eof occurred",
        r"\bssl(?:error)?:",
        r"ssl error",
        r"tls (?:connect|handshake)",
        r"certificate verify failed",
        r"\bsslerror\b",
    ),
    _rule(
        "network_connect",
        "network",
        "proxy_or_connection",
        "medium",
        r"failed to establish a new connection",
        r"network is unreachable",
        r"temporary failure in name resolution",
        r"could not resolve host",
        r"name or service not known",
        r"connection reset",
        r"remote end closed connection",
        r"remote disconnected",
        r"connection aborted",
        r"\bproxyerror\b",
        r"tunnel connection failed",
        r"connection refused",
        r"\bname resolution error\b",
    ),
    _rule(
        "timeout",
        "network",
        "request",
        "medium",
        r"timed out",
        r"\btimeouterror\b",
        r"\breadtimeout\b",
        r"read operation timed out",
        r"\bconnecttimeout\b",
    ),
    _rule(
        "extractor_parse",
        "extractor",
        "metadata",
        "medium",
        r"unable to extract",
        r"failed to extract",
        r"unable to parse",
    ),
)

_PRIMARY_PRIORITY = {
    code: index
    for index, code in enumerate(
        (
            "video_unavailable",
            "auth_cookies",
            "cookie_format",
            "geo_restricted",
            "pot_provider",
            "po_token",
            "policy_limit",
            "rate_limit",
            "http_forbidden",
            "proxy_upstream",
            "js_runtime",
            "ffmpeg",
            "format_unavailable",
            "local_io",
            "network_tls",
            "network_connect",
            "timeout",
            "media_delivery",
            "extractor_parse",
        )
    )
}


def _line_rules(line: str) -> list[_ErrorRule]:
    matches = [
        rule for rule in _ERROR_RULES if any(pattern.search(line) for pattern in rule.patterns)
    ]
    return sorted(matches, key=lambda rule: _PRIMARY_PRIORITY[rule.code])


def _redact_log_line(line: str) -> str:
    redacted = re.sub(r"https?://\S+", "<url>", line, flags=re.IGNORECASE)
    redacted = re.sub(r"(?i)(cookie|token|authorization)(?:\s|=|:)+\S+", r"\1=<value>", redacted)
    redacted = re.sub(r"[A-Za-z0-9_=-]{20,}", "<value>", redacted)
    return redacted


def _analyze_extractor_log(stderr: str) -> dict[str, object]:
    """Reduce possibly sensitive stderr to counts and stable signal codes."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    error_lines = [line for line in lines if "error:" in line.lower()]
    warning_lines = [line for line in lines if "warning:" in line.lower()]
    all_matches = [rule for line in lines for rule in _line_rules(line)]
    signals = list(dict.fromkeys(rule.code for rule in all_matches))
    candidates = list(reversed(error_lines or lines))
    primary_rule = next(
        (matches[0] for line in candidates if (matches := _line_rules(line))),
        None,
    )
    matched_line_scope = "terminal_error" if error_lines and primary_rule else "none"
    terminal_line = error_lines[-1] if error_lines else (lines[-1] if lines else "")
    redacted_terminal = _redact_log_line(terminal_line)
    http_statuses = sorted(
        set(
            re.findall(
                r"(?i)(?:http error|status(?: code)?)\D{0,6}([1-5]\d{2})",
                "\n".join(lines),
            )
        )
    )
    known_exceptions = [
        name
        for name in (
            "SSLError",
            "ProxyError",
            "TimeoutError",
            "ReadTimeout",
            "ConnectTimeout",
            "NameResolutionError",
            "ConnectionResetError",
            "ConnectionError",
            "BrokenPipeError",
            "HTTPError",
        )
        if name.lower() in stderr.lower()
    ]
    if primary_rule is None:
        exception_codes = {
            "SSLError": "network_tls",
            "ProxyError": "network_connect",
            "NameResolutionError": "network_connect",
            "ConnectionResetError": "network_connect",
            "ConnectionError": "network_connect",
            "BrokenPipeError": "network_connect",
            "TimeoutError": "timeout",
            "ReadTimeout": "timeout",
            "ConnectTimeout": "timeout",
        }
        exception_code = next(
            (exception_codes[name] for name in known_exceptions if name in exception_codes),
            None,
        )
        if exception_code is not None:
            primary_rule = next(rule for rule in _ERROR_RULES if rule.code == exception_code)
            matched_line_scope = "exception"
    if primary_rule is None:
        primary_rule = next(
            (matches[0] for line in reversed(lines) if (matches := _line_rules(line))),
            None,
        )
        if primary_rule is not None:
            matched_line_scope = "stderr"
    primary = primary_rule.code if primary_rule else "extractor"
    return {
        "primary": primary,
        "category": primary_rule.category if primary_rule else "unknown",
        "phase": primary_rule.phase if primary_rule else "extractor",
        "confidence": primary_rule.confidence if primary_rule else "low",
        "signals": signals,
        "stderr_present": bool(lines),
        "line_count": len(lines),
        "error_lines": len(error_lines),
        "warning_lines": len(warning_lines),
        "matched_line_scope": matched_line_scope,
        "http_statuses": http_statuses,
        "exception_types": known_exceptions,
        "terminal_fingerprint": (
            sha256(redacted_terminal.encode()).hexdigest()[:12] if terminal_line else None
        ),
        "raw_log_included": False,
    }


def _exception_analysis(
    code: str,
    *,
    category: str,
    phase: str,
    exception_type: str,
) -> dict[str, object]:
    """Describe a caught process exception without recording its potentially sensitive text."""
    return {
        "primary": code,
        "category": category,
        "phase": phase,
        "confidence": "high",
        "signals": [code],
        "stderr_present": False,
        "line_count": 0,
        "error_lines": 0,
        "warning_lines": 0,
        "matched_line_scope": "exception",
        "http_statuses": [],
        "exception_types": [exception_type],
        "terminal_fingerprint": None,
        "raw_log_included": False,
    }


def _classify_extractor_error(stderr: str) -> tuple[str, str, dict[str, object]]:
    analysis = _analyze_extractor_log(stderr)
    code = str(analysis["primary"])
    return code, _ERROR_MESSAGES.get(code, _ERROR_MESSAGES["extractor"]), analysis


def _safe_extractor_error(stderr: str) -> str:
    return _classify_extractor_error(stderr)[1]


def _profile_args(settings: Settings) -> list[str]:
    args = [
        "--concurrent-fragments",
        "1",
        "--abort-on-unavailable-fragments",
        "--sleep-requests",
        "1",
    ]
    if settings.youtube_profile == "baseline":
        return args
    try:
        version("bgutil-ytdlp-pot-provider")
    except PackageNotFoundError:
        raise MediaError(
            "The pot_bgutil profile requires the optional bgutil plugin.",
            code="profile_config",
        ) from None
    if settings.youtube_pot_provider_url is None:
        raise MediaError(
            "The pot_bgutil profile requires YOUTUBE_POT_PROVIDER_URL.",
            code="profile_config",
        )
    return [
        *args,
        "--extractor-args",
        "youtube:player-client=mweb",
        "--extractor-args",
        f"youtubepot-bgutilhttp:base_url={settings.youtube_pot_provider_url}",
    ]


def _run(
    settings: Settings,
    args: list[str],
    timeout: int,
    *,
    log_capture: dict[str, object] | None = None,
    socket_timeout: int = 20,
    token: CancellationToken | None = None,
) -> str:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-playlist",
        "--socket-timeout",
        str(socket_timeout),
        "--retries",
        "0",
        "--extractor-retries",
        "0",
        "--fragment-retries",
        "0",
        *_profile_args(settings),
    ]
    if shutil.which("deno") is None and shutil.which("node") is not None:
        command += ["--js-runtimes", "node"]
    if settings.youtube_proxy is not None:
        command += ["--proxy", str(settings.youtube_proxy)]
    with working_cookie_file(settings.youtube_cookie_file) as cookie_file:
        if cookie_file is not None:
            command += ["--cookies", str(cookie_file)]
        try:
            result = DEFAULT_PROCESS_RUNNER.run(
                command + args,
                timeout=timeout,
                token=token,
            )
        except MediaError as error:
            if error.code not in {"timeout", "cancelled", "process_start"}:
                raise
            phase = "process_cancel" if error.code == "cancelled" else "process_deadline"
            if error.code == "process_start":
                phase = "startup"
            analysis = _exception_analysis(
                error.code,
                category="process",
                phase=phase,
                exception_type="Cancelled" if error.code == "cancelled" else type(error).__name__,
            )
            raise MediaError(
                str(error),
                code=error.code,
                log_analysis=analysis,
            ) from None
    analysis = _analyze_extractor_log(result.stderr)
    if log_capture is not None:
        log_capture.update(analysis)
    if result.returncode:
        # Raw extractor errors may contain signed URLs or account details.
        code, message, analysis = _classify_extractor_error(result.stderr)
        raise MediaError(message, code=code, log_analysis=analysis)
    return result.stdout


def probe(settings: Settings, url: str, *, log_capture: dict[str, object] | None = None) -> dict:
    canonical = youtube_url(url)
    expected_id = parse_qs(urlsplit(canonical).query)["v"][0]
    output = _run(
        settings,
        ["--skip-download", "--dump-single-json", canonical],
        90,
        log_capture=log_capture,
    )
    try:
        info = json.loads(output, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise MediaError("Downloader returned invalid metadata.", code="metadata_invalid") from None
    return VideoMetadata.from_mapping(info, expected_id=expected_id).to_dict(compact=True)


_SAVED_METADATA_KEYS = (
    "id",
    "title",
    "duration",
    "availability",
    "live_status",
    "webpage_url",
    "channel",
    "channel_id",
    "uploader",
    "uploader_id",
    "upload_date",
    "timestamp",
    "width",
    "height",
    "fps",
    "vcodec",
    "acodec",
    "format_id",
    "format_note",
    "ext",
)


def _download_metadata(output: str, *, expected_id: str, max_duration: int) -> VideoMetadata:
    """Parse yt-dlp JSON output and retain only portable, non-request metadata."""
    for line in reversed(output.splitlines()):
        try:
            info = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(info, dict):
            safe = {key: info.get(key) for key in _SAVED_METADATA_KEYS}
            return VideoMetadata.from_mapping(
                safe, expected_id=expected_id, max_duration=max_duration
            )
    raise MediaError("Downloader returned invalid metadata.", code="metadata_invalid")


def download(
    settings: Settings,
    url: str,
    directory: Path,
    *,
    metadata_out: dict[str, object] | None = None,
    token: CancellationToken | None = None,
) -> Path:
    canonical = youtube_url(url)
    if shutil.which("ffmpeg"):
        format_selector = (
            "bestvideo[height<=720][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
            "best[height<=720][ext=mp4]/best[height<=720]"
        )
        merge_args = ["--merge-output-format", "mp4"]
    else:
        # Progressive formats contain audio and video and do not need FFmpeg.
        format_selector = "best[height<=720][ext=mp4]/best[height<=720]"
        merge_args = []
    metadata_args = ["--no-simulate", "--print-json"] if metadata_out is not None else []
    run_kwargs: dict[str, object] = {"socket_timeout": 45}
    if token is not None:
        run_kwargs["token"] = token
    output = _run(
        settings,
        [
            "--quiet",
            "--no-progress",
            *metadata_args,
            "--no-overwrites",
            "--max-filesize",
            f"{settings.max_download_mb}M",
            "--match-filter",
            f"duration > 0 & duration <= {settings.max_duration_seconds} & live_status = not_live",
            "-f",
            format_selector,
            *merge_args,
            "-o",
            str(directory / "video.%(ext)s"),
            canonical,
        ],
        300,
        **run_kwargs,
    )
    files = [p for p in directory.glob("video.*") if p.suffix in {".mp4", ".webm", ".mkv"}]
    if len(files) != 1:
        raise MediaError(
            "No supported video downloaded; it may exceed the size limit.",
            code="download_output",
        )
    path = files[0]
    if not 0 < path.stat().st_size <= settings.max_download_mb * 1024 * 1024:
        raise MediaError(
            "Downloaded file exceeds the configured upload limit.", code="upload_limit"
        )
    if metadata_out is not None:
        video_id = parse_qs(urlsplit(canonical).query)["v"][0]
        metadata_out.update(
            _download_metadata(
                output,
                expected_id=video_id,
                max_duration=settings.max_duration_seconds,
            ).to_dict()
        )
    return path


def download_artifact(
    settings: Settings,
    url: str,
    directory: Path,
    *,
    token: CancellationToken | None = None,
) -> DownloadArtifact:
    metadata: dict[str, object] = {}
    path = download(settings, url, directory, metadata_out=metadata, token=token)
    canonical = youtube_url(url)
    video_id = parse_qs(urlsplit(canonical).query)["v"][0]
    model = VideoMetadata.from_mapping(
        metadata,
        expected_id=video_id,
        max_duration=settings.max_duration_seconds,
    )
    return DownloadArtifact(path=path, metadata=model)


def _error_record(code: str, message: str, **extra: str) -> dict[str, object]:
    return error_record(code, message, **extra)


def media_error_report(error: MediaError) -> dict[str, object]:
    """Create the same secret-safe error shape for probe and download commands."""
    return _media_error_report(error)


def diagnostic_manifest(settings: Settings, url: str) -> dict[str, object]:
    """Perform exactly one extractor attempt and return a secret-safe decision record."""
    started = time.monotonic()
    manifest: dict[str, object] = {
        "schema_version": 3,
        "checked_at": datetime.now(UTC).isoformat(),
        "operation": "probe",
        "extractor_attempts": 0,
        "automatic_retries": 0,
        "runtime": runtime_report(settings),
        "log_analysis": {
            "primary": None,
            "category": None,
            "phase": None,
            "confidence": None,
            "signals": [],
            "stderr_present": False,
            "line_count": 0,
            "error_lines": 0,
            "warning_lines": 0,
            "matched_line_scope": "none",
            "http_statuses": [],
            "exception_types": [],
            "terminal_fingerprint": None,
            "raw_log_included": False,
        },
    }
    try:
        canonical = youtube_url(url)
    except ValueError as error:
        manifest.update(
            status="error",
            video_id=None,
            error=_error_record("invalid_url", str(error)),
        )
        manifest["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        return manifest
    manifest["video_id"] = parse_qs(urlsplit(canonical).query)["v"][0]
    safe_log: dict[str, object] = {}
    try:
        manifest["extractor_attempts"] = 1
        manifest.update(status="ok", metadata=probe(settings, canonical, log_capture=safe_log))
    except MediaError as error:
        manifest.update(
            status="error",
            error=_error_record(error.code, str(error)),
        )
        if error.log_analysis is not None:
            safe_log.update(error.log_analysis)
    except OSError:
        manifest.update(
            status="error",
            error=_error_record("local_io", "A local file operation failed during diagnosis."),
        )
    # This is the diagnostic safety boundary: no unexpected exception or message may escape.
    except Exception as error:  # noqa: BLE001
        manifest.update(
            status="error",
            error=_error_record(
                "internal_error",
                "An unexpected internal diagnostic error was safely contained.",
                exception_type=type(error).__name__,
            ),
        )
    if safe_log:
        manifest["log_analysis"] = safe_log
    manifest["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return manifest
