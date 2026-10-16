import argparse
import asyncio
import json

from pydantic import ValidationError

from .config import Settings
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
    try:
        settings = Settings()
    except ValidationError as error:
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
    try:
        if args.doctor:
            _write(runtime_report(settings))
        elif args.check:
            settings.require_bot()
            _write({"status": "ok", "message": "Bot configuration is present."})
        elif args.probe:
            _write(probe(settings, args.probe))
        elif args.diagnose:
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
        else:
            from .bot import run_bot

            asyncio.run(run_bot(settings))
    except MediaError as error:
        _write(media_error_report(error))
        return 1
    except ValueError:
        _write({"status": "error", "error": error_record("invalid_url")})
        return 1
    except OSError:
        _write({"status": "error", "error": error_record("local_io")})
        return 1
    except KeyboardInterrupt:
        _write({"status": "error", "error": error_record("cancelled")})
        return 130
    except Exception as error:  # noqa: BLE001
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
