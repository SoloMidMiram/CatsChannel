import argparse
import asyncio
import json

from pydantic import ValidationError

from .config import Settings
from .diagnostics import configure_logging, log_failure
from .errors import MediaError, error_record, media_error_report
from .library import list_downloads, verify_download
from .media import diagnostic_manifest, probe, runtime_report
from .services.media_service import MediaService


def _write(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CatsChannel admin-only integration demo")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--doctor", action="store_true", help="safe local runtime diagnostics")
    actions.add_argument("--check", action="store_true", help="offline configuration validation")
    actions.add_argument("--bot", action="store_true")
    actions.add_argument(
        "--bot-diagnose",
        action="store_true",
        help="read-only Bot API connectivity, webhook and channel-permission checks",
    )
    actions.add_argument(
        "--telegram-login", action="store_true", help="interactive Telegram user-account login"
    )
    actions.add_argument(
        "--telegram-diagnose",
        action="store_true",
        help="one-attempt read-only Telethon connection and authorization diagnosis",
    )
    actions.add_argument("--probe", metavar="URL")
    actions.add_argument(
        "--diagnose", metavar="URL", help="one-attempt secret-safe diagnostic manifest"
    )
    actions.add_argument("--download", metavar="URL")
    actions.add_argument("--list-downloads", action="store_true", help="list the media library")
    actions.add_argument("--verify-download", metavar="VIDEO_ID", help="verify one stored item")
    return parser


def main() -> int:
    args = _parser().parse_args()
    operation = next(
        (
            name.removeprefix("--").replace("-", "_")
            for name, selected in (
                ("--doctor", args.doctor),
                ("--check", args.check),
                ("--bot", args.bot),
                ("--bot-diagnose", args.bot_diagnose),
                ("--telegram-login", args.telegram_login),
                ("--telegram-diagnose", args.telegram_diagnose),
                ("--probe", args.probe is not None),
                ("--diagnose", args.diagnose is not None),
                ("--download", args.download is not None),
                ("--list-downloads", args.list_downloads),
                ("--verify-download", args.verify_download is not None),
            )
            if selected
        ),
        "unknown",
    )
    logger = configure_logging()
    try:
        settings = Settings()
    except ValidationError as error:
        diagnostic = MediaError(
            code="invalid_config",
            log_analysis={
                "phase": "configuration",
                "exception_types": [type(error).__name__],
                "raw_log_included": False,
            },
        )
        log_failure(logger, "cli_failure", diagnostic, operation=operation)
        fields = ", ".join(".".join(map(str, item["loc"])) for item in error.errors())
        _write(
            {
                "status": "error",
                "error": error_record(
                    "invalid_config",
                    "Configuration validation failed; values are hidden.",
                    fields=fields,
                ),
            }
        )
        return 1
    logger = configure_logging(settings.log_level)
    try:
        if args.doctor:
            _write(runtime_report(settings))
        elif args.check:
            settings.require_bot()
            _write({"status": "ok", "message": "Bot configuration is present."})
        elif args.bot_diagnose:
            from .bot.preflight import diagnose_bot_api

            report = asyncio.run(diagnose_bot_api(settings))
            _write(report)
            return 0 if report["status"] == "ready" else 1
        elif args.probe:
            if settings.media_backend == "telegram_bot":
                raise MediaError(code="backend_capability")
            _write(probe(settings, args.probe))
        elif args.diagnose:
            if settings.media_backend == "telegram_bot":
                raise MediaError(code="backend_capability")
            manifest = diagnostic_manifest(settings, args.diagnose)
            _write(manifest)
            return 0 if manifest["status"] == "ok" else 1
        elif args.download:
            _write(MediaService(settings).acquire(args.download).to_dict())
        elif args.list_downloads:
            _write(list_downloads(settings))
        elif args.verify_download:
            result = verify_download(settings, args.verify_download)
            _write(result)
            return 0 if result["status"] == "ok" else 1
        elif args.telegram_login:
            from .adapters.telegram_downloader import login

            _write(asyncio.run(login(settings)))
        elif args.telegram_diagnose:
            from .adapters.telegram_downloader import diagnose_connection

            report = asyncio.run(diagnose_connection(settings))
            _write(report)
            return 0 if report["status"] == "ok" else 1
        else:
            from .bot import run_bot

            asyncio.run(run_bot(settings))
    except MediaError as error:
        log_failure(logger, "cli_failure", error, operation=operation)
        _write(media_error_report(error))
        return 130 if error.code == "cancelled" else 1
    except ValueError as error:
        log_failure(
            logger,
            "cli_failure",
            MediaError(
                code="invalid_url",
                log_analysis={
                    "phase": operation,
                    "exception_types": [type(error).__name__],
                    "raw_log_included": False,
                },
            ),
            operation=operation,
        )
        _write({"status": "error", "error": error_record("invalid_url")})
        return 1
    except TimeoutError as error:
        if operation == "bot":
            from .bot.errors import bot_api_diagnostic_error

            diagnostic = bot_api_diagnostic_error(error)
            log_failure(logger, "cli_failure", diagnostic, operation=operation)
            _write(media_error_report(diagnostic))
            return 1
        log_failure(
            logger,
            "cli_failure",
            MediaError(
                code="local_io",
                log_analysis={
                    "phase": operation,
                    "exception_types": [type(error).__name__],
                    "raw_log_included": False,
                },
            ),
            operation=operation,
        )
        _write({"status": "error", "error": error_record("local_io")})
        return 1
    except OSError as error:
        log_failure(
            logger,
            "cli_failure",
            MediaError(
                code="local_io",
                log_analysis={
                    "phase": operation,
                    "exception_types": [type(error).__name__],
                    "raw_log_included": False,
                },
            ),
            operation=operation,
        )
        _write({"status": "error", "error": error_record("local_io")})
        return 1
    except KeyboardInterrupt as error:
        log_failure(
            logger,
            "cli_failure",
            MediaError(
                code="cancelled",
                log_analysis={
                    "phase": operation,
                    "exception_types": [type(error).__name__],
                    "raw_log_included": False,
                },
            ),
            operation=operation,
        )
        _write({"status": "error", "error": error_record("cancelled")})
        return 130
    except Exception as error:  # noqa: BLE001 - recognize the safe Bot API boundary first
        from aiogram.exceptions import TelegramNetworkError

        if isinstance(error, TelegramNetworkError):
            from .bot.errors import bot_api_diagnostic_error

            diagnostic = bot_api_diagnostic_error(error)
            log_failure(logger, "cli_failure", diagnostic, operation=operation)
            _write(media_error_report(diagnostic))
            return 1
        log_failure(logger, "cli_failure", error, operation=operation)
        _write(
            {
                "status": "error",
                "error": error_record(
                    "internal_error",
                    exception_type=type(error).__name__,
                ),
            }
        )
        return 1
    return 0
