"""Pure normalization for individual YouTube video links."""

import re
from urllib.parse import parse_qs, urlsplit


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
