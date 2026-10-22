from asyncio import CancelledError
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ErrorPolicy:
    message: str
    action: str
    retry_policy: str


_DEFAULT = ErrorPolicy(
    "Media processing failed.",
    "Inspect the safe diagnostic record before another attempt.",
    "after_investigation",
)


ERROR_POLICIES = MappingProxyType(
    {
        "reply_entry_invalid": ErrorPolicy(
            "This reply link is invalid or unavailable.",
            "Open a current reply link or use /help.",
            "after_local_fix",
        ),
        "telegram_config": ErrorPolicy(
            "Telegram client configuration or the optional userbot dependency is missing.",
            "Install the userbot extra and set TELEGRAM_API_ID and TELEGRAM_API_HASH locally.",
            "after_local_fix",
        ),
        "telegram_login": ErrorPolicy(
            "A logged-in Telegram user session is required.",
            "Run --telegram-login interactively in your own terminal.",
            "after_local_fix",
        ),
        "telegram_api_credentials": ErrorPolicy(
            "Telegram rejected the API ID or API hash.",
            "Verify TELEGRAM_API_ID and TELEGRAM_API_HASH against my.telegram.org/apps.",
            "after_local_fix",
        ),
        "telegram_phone": ErrorPolicy(
            "Telegram rejected or restricted the supplied phone number.",
            "Verify the full international number and inspect the account in the official app.",
            "after_investigation",
        ),
        "telegram_login_code": ErrorPolicy(
            "Telegram rejected or expired the login code.",
            "Start one fresh login attempt and enter only its newest code.",
            "explicit_only",
        ),
        "telegram_password": ErrorPolicy(
            "Telegram rejected the two-step-verification password.",
            "Verify the password in the official Telegram app before one new login attempt.",
            "explicit_only",
        ),
        "telegram_connect": ErrorPolicy(
            "Could not establish the Telegram MTProto connection.",
            "Check TELEGRAM_PROXY and the proxy route before one later attempt.",
            "after_network_change",
        ),
        "telegram_session_io": ErrorPolicy(
            "The local Telegram session database could not be accessed safely.",
            "Stop other clients using this session and check its directory permissions.",
            "after_local_fix",
        ),
        "telegram_server": ErrorPolicy(
            "Telegram returned a temporary server-side failure.",
            "Stop and make one later attempt after a cooldown; do not resend in a loop.",
            "after_cooldown",
        ),
        "telegram_busy": ErrorPolicy(
            "The Telegram session is already in use or has a leftover operation lock.",
            "Wait for the other operation; inspect stale locks only after all clients stop.",
            "explicit_only",
        ),
        "telegram_bot_flow": ErrorPolicy(
            "The downloader bot did not follow the direct-video workflow.",
            "Check the conversation manually for buttons, audio-only output, or access prompts.",
            "after_investigation",
        ),
        "telegram_flood_wait": ErrorPolicy(
            "Telegram requested a cooldown. No automatic retry was made.",
            "Wait and inspect the session before making another explicit request.",
            "after_cooldown",
        ),
        "telegram_download": ErrorPolicy(
            "The Telegram downloader operation failed.",
            "Check Telegram connectivity and the bot conversation; do not resend in a loop.",
            "after_investigation",
        ),
        "telegram_upload": ErrorPolicy(
            "Telegram could not upload the validated media file.",
            "Inspect the private chat, connectivity and upload limits before deciding to retry.",
            "after_reconciliation",
        ),
        "telegram_publish": ErrorPolicy(
            "Telegram could not publish to the configured channel.",
            "Inspect channel history and posting permissions; do not blindly resend.",
            "after_reconciliation",
        ),
        "backend_capability": ErrorPolicy(
            "This backend does not support a metadata-only YouTube probe.",
            "Use --download with the Telegram backend; it never contacts YouTube directly.",
            "explicit_only",
        ),
        "invalid_url": ErrorPolicy(
            "The supplied URL is not a supported YouTube video URL.",
            "Replace the URL; do not contact YouTube.",
            "after_local_fix",
        ),
        "invalid_config": ErrorPolicy(
            "Configuration validation failed.",
            "Correct the reported configuration fields before starting the command.",
            "after_local_fix",
        ),
        "network_connect": ErrorPolicy(
            "Could not connect to YouTube from this environment.",
            "Repair DNS/proxy, then make one diagnostic attempt.",
            "after_network_change",
        ),
        "network_tls": ErrorPolicy(
            "The TLS connection to YouTube failed.",
            "Switch or repair the proxy route, then make one diagnostic attempt.",
            "after_network_change",
        ),
        "timeout": ErrorPolicy(
            "The extractor timed out during a network read or connection timeout.",
            "Check proxy health and wait before one later attempt.",
            "after_health_check_or_cooldown",
        ),
        "cancelled": ErrorPolicy(
            "The media operation was cancelled.",
            "Start a new operation only after cancellation cleanup completes.",
            "explicit_only",
        ),
        "proxy_upstream": ErrorPolicy(
            "The proxy or its upstream returned a temporary server failure.",
            "Switch or repair the proxy upstream, then make one later attempt.",
            "after_network_change",
        ),
        "rate_limit": ErrorPolicy(
            "YouTube or the proxy reported a request-rate limit.",
            "Stop and cool down; do not retry until the limit window has passed.",
            "after_cooldown",
        ),
        "http_forbidden": ErrorPolicy(
            "YouTube rejected the request with HTTP 403.",
            "Check proxy reputation and PO-token guidance before one later attempt.",
            "after_investigation",
        ),
        "geo_restricted": ErrorPolicy(
            "The video is unavailable from the current region.",
            "Stop or use an authorized route in an available region.",
            "do_not_retry_same_route",
        ),
        "video_unavailable": ErrorPolicy(
            "The video is unavailable, private, or restricted.",
            "Stop and replace the video URL.",
            "do_not_retry",
        ),
        "auth_cookies": ErrorPolicy(
            "YouTube requires authenticated cookies for this request.",
            "Refresh the cookie export once; do not retry the same jar repeatedly.",
            "after_cookie_refresh",
        ),
        "cookie_format": ErrorPolicy(
            "The configured cookie file is not valid Netscape cookie data.",
            "Export a valid Netscape-format cookie file, then retry once.",
            "after_local_fix",
        ),
        "cookie_missing": ErrorPolicy(
            "The configured cookie file does not exist.",
            "Correct YOUTUBE_COOKIE_FILE before any network attempt.",
            "after_local_fix",
        ),
        "profile_config": ErrorPolicy(
            "The selected YouTube profile is not completely configured.",
            "Complete the selected profile locally before any network attempt.",
            "after_local_fix",
        ),
        "proxy_config": ErrorPolicy(
            "The configured YouTube proxy is invalid.",
            "Correct YOUTUBE_PROXY before any network attempt.",
            "after_local_fix",
        ),
        "local_io": ErrorPolicy(
            "A local file operation failed.",
            "Repair local file/temp permissions before any network attempt.",
            "after_local_fix",
        ),
        "cleanup_failed": ErrorPolicy(
            "Media cleanup did not complete.",
            "Inspect the operation staging directory before another attempt.",
            "after_local_fix",
        ),
        "process_start": ErrorPolicy(
            "Could not start the required media process.",
            "Repair the local runtime before any network attempt.",
            "after_local_fix",
        ),
        "js_runtime": ErrorPolicy(
            "YouTube extraction requires a supported JavaScript runtime.",
            "Install or select Node/Deno before retrying.",
            "after_local_fix",
        ),
        "po_token": ErrorPolicy(
            "YouTube requires a PO token for this request.",
            "Configure a supported PO-token provider before retrying.",
            "after_provider_setup",
        ),
        "pot_provider": ErrorPolicy(
            "The configured PO-token provider failed or was unavailable.",
            "Repair the provider/plugin connection before retrying.",
            "after_provider_repair",
        ),
        "ffmpeg": ErrorPolicy(
            "FFmpeg is required for this media operation.",
            "Install FFmpeg before retrying the download.",
            "after_local_fix",
        ),
        "policy_limit": ErrorPolicy(
            "The video violates the configured media policy.",
            "Stop; the video violates the configured media policy.",
            "do_not_retry",
        ),
        "format_unavailable": ErrorPolicy(
            "YouTube did not expose a supported media format.",
            "Review format policy and PO-token guidance before retrying.",
            "after_investigation",
        ),
        "media_delivery": ErrorPolicy(
            "Metadata was found, but media transfer failed.",
            "Repair the media-CDN route or token setup before retrying.",
            "after_network_or_token_change",
        ),
        "media_validation": ErrorPolicy(
            "The downloaded file failed local playback validation.",
            "Inspect FFprobe and the staged media before another download.",
            "after_local_investigation",
        ),
        "cache_corrupt": ErrorPolicy(
            "The stored media item does not match its manifest.",
            "Quarantine or remove the item explicitly before reacquiring it.",
            "after_local_fix",
        ),
        "metadata_invalid": ErrorPolicy(
            "The downloader returned invalid metadata.",
            "Inspect the yt-dlp version; do not retry in a loop.",
            "after_investigation",
        ),
        "download_output": ErrorPolicy(
            "The downloader did not produce exactly one supported media file.",
            "Inspect the selected format and staged output before retrying.",
            "after_investigation",
        ),
        "upload_limit": ErrorPolicy(
            "The downloaded file exceeds the configured upload limit.",
            "Stop or explicitly change the media policy.",
            "do_not_retry",
        ),
        "extractor_parse": ErrorPolicy(
            "yt-dlp could not parse the expected YouTube response.",
            "Review or update yt-dlp before retrying.",
            "after_version_review",
        ),
        "extractor": ErrorPolicy(
            "YouTube extraction failed.",
            "Inspect the yt-dlp release and safe category; do not retry in a loop.",
            "after_investigation",
        ),
        "submission_media_invalid": ErrorPolicy(
            "The submission does not contain valid media evidence.",
            "Validate the media before creating a submission.",
            "after_local_fix",
        ),
        "source_identity_unresolved": ErrorPolicy(
            "The media source could not be verified.",
            "Explicitly select an existing logical source thread.",
            "explicit_only",
        ),
        "source_identity_conflict": ErrorPolicy(
            "The selected source conflicts with verified source identity.",
            "Use the verified source thread or cancel the submission.",
            "do_not_retry_unchanged",
        ),
        "source_selection_invalid": ErrorPolicy(
            "The selected logical source thread is unavailable or incompatible.",
            "Select an existing thread for the same source provider.",
            "after_local_fix",
        ),
        "duplicate_media": ErrorPolicy(
            "This source media already has a submission.",
            "Load the existing submission instead of creating a duplicate.",
            "do_not_retry",
        ),
        "handoff_invalid": ErrorPolicy(
            "The media handoff is invalid, expired, mismatched, or already used.",
            "Start one new correlated handoff; do not replay the old response.",
            "explicit_only",
        ),
        "submission_persistence": ErrorPolicy(
            "The submission could not be stored safely.",
            "Reconcile the handoff and database state before one explicit retry.",
            "after_reconciliation",
        ),
        "intake_conflict": ErrorPolicy(
            "This intake conflicts with its stored owner or placement.",
            "Cancel and start from the original post entry; do not transfer the media again.",
            "after_reconciliation",
        ),
        "intake_persistence": ErrorPolicy(
            "The intake state could not be reconciled safely.",
            "Inspect the stored projection and intent before one explicit retry.",
            "after_reconciliation",
        ),
        "intake_superseded": ErrorPolicy(
            "This intake was replaced by a newer command.",
            "Continue with the newest active post flow.",
            "do_not_retry",
        ),
        "intake_unavailable": ErrorPolicy(
            "Bot submission intake is not configured.",
            "Enable persistence and restart the bot before using /post.",
            "after_local_fix",
        ),
        "internal_error": ErrorPolicy(
            "An unexpected internal error was safely contained.",
            "Inspect local application logs/code; no automatic retry is allowed.",
            "after_code_investigation",
        ),
    }
)


class MediaError(RuntimeError):
    def __init__(
        self,
        message: str | None = None,
        *,
        code: str = "media_error",
        log_analysis: dict[str, object] | None = None,
        warnings: tuple[str, ...] = (),
    ) -> None:
        policy = ERROR_POLICIES.get(code, _DEFAULT)
        super().__init__(message or policy.message)
        self.code = code
        self.log_analysis = log_analysis
        self.warnings = warnings


def cleanup_warning_error(primary: BaseException, warning: str) -> MediaError:
    """Preserve the primary classification without exposing arbitrary exception text."""
    if isinstance(primary, MediaError):
        primary.warnings += (warning,)
        return primary
    if isinstance(primary, (KeyboardInterrupt, CancelledError)):
        code = "cancelled"
    elif isinstance(primary, OSError):
        code = "local_io"
    elif isinstance(primary, ValueError):
        code = "invalid_url"
    else:
        code = "internal_error"
    return MediaError(code=code, warnings=(warning,))


def error_record(code: str, message: str | None = None, **extra: str) -> dict[str, object]:
    policy = ERROR_POLICIES.get(code, _DEFAULT)
    return {
        "code": code,
        "message": message or policy.message,
        "action": policy.action,
        "retry_policy": policy.retry_policy,
        **extra,
    }


def media_error_report(error: MediaError) -> dict[str, object]:
    report: dict[str, Any] = {
        "status": "error",
        "error": error_record(error.code, str(error)),
    }
    if error.log_analysis is not None:
        report["log_analysis"] = error.log_analysis
    if error.warnings:
        report["warnings"] = list(error.warnings)
    return report
