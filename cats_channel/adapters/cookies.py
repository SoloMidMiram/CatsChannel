import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..errors import MediaError


def cookie_health(path: Path) -> dict[str, object]:
    """Inspect cookie structure and expiry without exposing cookie names or values."""
    report: dict[str, object] = {
        "cookie_file_readable": False,
        "cookie_file_format_valid": False,
        "cookie_file_newline_style": None,
        "cookie_file_entries": 0,
        "cookie_file_youtube_entries": 0,
        "cookie_file_expired_entries": 0,
        "cookie_file_session_entries": 0,
    }
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError):
        return report
    report["cookie_file_readable"] = True
    has_crlf = b"\r\n" in raw
    has_lf = b"\n" in raw.replace(b"\r\n", b"")
    report["cookie_file_newline_style"] = (
        "mixed" if has_crlf and has_lf else "crlf" if has_crlf else "lf" if has_lf else "none"
    )
    lines = text.splitlines()
    header_valid = bool(lines) and lines[0].strip() in {
        "# HTTP Cookie File",
        "# Netscape HTTP Cookie File",
    }
    rows = [
        line
        for line in lines[1:]
        if line.strip() and (not line.startswith("#") or line.startswith("#HttpOnly_"))
    ]
    rows_valid = True
    now = int(time.time())
    for row in rows:
        fields = row.split("\t")
        if len(fields) != 7:
            rows_valid = False
            continue
        domain = fields[0].removeprefix("#HttpOnly_").lower().lstrip(".")
        try:
            expires = int(fields[4])
        except ValueError:
            rows_valid = False
            continue
        report["cookie_file_entries"] = int(report["cookie_file_entries"]) + 1
        if domain == "youtube.com" or domain.endswith(".youtube.com"):
            report["cookie_file_youtube_entries"] = int(report["cookie_file_youtube_entries"]) + 1
        if expires == 0:
            report["cookie_file_session_entries"] = int(report["cookie_file_session_entries"]) + 1
        elif expires <= now:
            report["cookie_file_expired_entries"] = int(report["cookie_file_expired_entries"]) + 1
    report["cookie_file_format_valid"] = header_valid and rows_valid
    return report


@contextmanager
def working_cookie_file(source: Path | None) -> Iterator[Path | None]:
    """Give yt-dlp a private working jar and never the source cookie export."""
    if source is None:
        yield None
        return
    if not source.is_file():
        raise MediaError(code="cookie_missing")
    try:
        with tempfile.TemporaryDirectory(prefix="cats-channel-cookies-") as folder:
            working = Path(folder) / "cookies.txt"
            shutil.copyfile(source, working)
            working.chmod(0o600)
            yield working
    except MediaError:
        raise
    except OSError:
        raise MediaError(
            "Could not create the private working cookie copy.", code="local_io"
        ) from None
