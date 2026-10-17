"""Trusted source-identity adapter contracts and local-library policy."""

from __future__ import annotations

from typing import Protocol

from ..persistence.entities import SourceIdentity
from .entities import ResolvedSourceIdentity, SubmissionMedia, ValidatedLocalMedia


class SourceIdentityResolver(Protocol):
    async def resolve(self, media: SubmissionMedia) -> ResolvedSourceIdentity: ...


class LibraryManifestSourceResolver:
    """Trust channel identity only from CatsChannel's direct yt-dlp adapter."""

    async def resolve(self, media: SubmissionMedia) -> ResolvedSourceIdentity:
        source = media.source_metadata
        if (
            isinstance(media, ValidatedLocalMedia)
            and media.backend == "yt_dlp"
            and source.channel_id is not None
        ):
            return ResolvedSourceIdentity(
                status="verified",
                identity=SourceIdentity(
                    provider=media.source_provider,
                    channel_id=source.channel_id,
                    channel_name=source.channel_name,
                    channel_username=source.channel_username,
                ),
                method="direct_extractor_metadata",
                evidence={"adapter": "yt_dlp", "stable_channel_id": True},
            )
        return ResolvedSourceIdentity(
            status="unresolved",
            identity=None,
            method="identity_not_verified",
            evidence={"adapter": getattr(media, "backend", media.origin)},
        )
