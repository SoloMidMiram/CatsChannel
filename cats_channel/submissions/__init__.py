"""Source-aware submission application boundary."""

from .entities import (
    HandoffBinding,
    HandoffClaim,
    IssuedHandoff,
    MediaValidationEvidence,
    ResolvedSourceIdentity,
    SourceMetadata,
    SubmissionRequest,
    SubmissionResult,
    SubmissionVideoMetadata,
    TelegramMetadataEvidence,
    ValidatedLocalMedia,
    ValidatedTelegramMedia,
)
from .errors import SubmissionError
from .library_adapter import local_media_from_library_item
from .resolvers import LibraryManifestSourceResolver, SourceIdentityResolver
from .service import SubmissionService

__all__ = [
    "HandoffBinding",
    "HandoffClaim",
    "IssuedHandoff",
    "LibraryManifestSourceResolver",
    "MediaValidationEvidence",
    "ResolvedSourceIdentity",
    "SourceIdentityResolver",
    "SourceMetadata",
    "SubmissionError",
    "SubmissionRequest",
    "SubmissionResult",
    "SubmissionService",
    "SubmissionVideoMetadata",
    "TelegramMetadataEvidence",
    "ValidatedLocalMedia",
    "ValidatedTelegramMedia",
    "local_media_from_library_item",
]
