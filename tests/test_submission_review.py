from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_submission_contracts import library_item

from cats_channel.persistence.entities import TelegramMessageRef
from cats_channel.submissions import (
    MediaValidationEvidence,
    ResolvedSourceIdentity,
    SubmissionError,
    SubmissionRequest,
    SubmissionService,
    SubmissionVideoMetadata,
    ValidatedTelegramMedia,
    local_media_from_library_item,
)


@pytest.mark.parametrize(
    "extra",
    [
        {"bot_token": "credential-marker"},
        {"private_message_text": "private-marker"},
        {"raw_response": {"authorization": "credential-marker"}},
        {"receipt": {"backend": "telegram_bot", "session": "credential-marker"}},
        {"acquisition_backend": "credential-marker"},
    ],
)
async def test_unexpected_media_provenance_never_reaches_repository(tmp_path, extra):
    media = local_media_from_library_item(library_item(tmp_path))
    media = replace(media, provenance={**media.provenance, **extra})
    factory = MagicMock()
    resolver = AsyncMock()
    resolver.resolve.return_value = ResolvedSourceIdentity(
        status="unresolved", identity=None, method="identity_not_verified"
    )
    service = SubmissionService(factory, resolver)

    with pytest.raises(SubmissionError) as caught:
        await service.submit(SubmissionRequest(media))

    assert caught.value.code == "submission_media_invalid"
    assert "marker" not in str(caught.value)
    factory.assert_not_called()


@pytest.mark.parametrize("evidence", [{"raw_payload": "private-marker"}, {"adapter": "secret"}])
async def test_unexpected_resolution_evidence_never_reaches_repository(tmp_path, evidence):
    media = local_media_from_library_item(library_item(tmp_path))
    factory = MagicMock()
    resolver = AsyncMock()
    resolver.resolve.return_value = ResolvedSourceIdentity(
        status="unresolved", identity=None, method="identity_not_verified", evidence=evidence
    )

    with pytest.raises(SubmissionError) as caught:
        await SubmissionService(factory, resolver).submit(SubmissionRequest(media))

    assert caught.value.code == "submission_media_invalid"
    factory.assert_not_called()


def test_telegram_identity_cannot_alias_one_file(tmp_path):
    evidence = local_media_from_library_item(library_item(tmp_path)).validation
    with pytest.raises(SubmissionError) as caught:
        ValidatedTelegramMedia(
            source_provider="telegram",
            source_media_id="message-derived-id",
            file_unique_id="canonical-file",
            file_id="downloadable-file",
            reference=TelegramMessageRef(200, 1),
            metadata=SubmissionVideoMetadata(None, 12.5),
            validation=evidence,
        )
    assert caught.value.code == "submission_media_invalid"


def test_external_payload_cannot_construct_validated_submission():
    with pytest.raises(SubmissionError):
        SubmissionRequest(media={"origin": "telegram_native", "full_decode": True})


async def test_service_rejects_external_payload_before_resolver_or_transaction():
    factory, resolver = MagicMock(), AsyncMock()
    with pytest.raises(SubmissionError):
        await SubmissionService(factory, resolver).submit({"media": {"full_decode": True}})
    factory.assert_not_called()
    resolver.resolve.assert_not_called()


def test_truthy_external_decode_claim_is_not_validation_evidence(tmp_path):
    evidence = local_media_from_library_item(library_item(tmp_path)).validation
    with pytest.raises(ValueError):
        MediaValidationEvidence(**{**evidence.__dict__, "full_decode": "passed"})


def test_manifest_adapter_excludes_external_payloads(tmp_path):
    item = library_item(tmp_path, backend="telegram_bot")
    item.manifest["acquisition"]["receipt"]["raw_payload"] = {"bot_token": "secret"}
    item.manifest["private_message_text"] = "private-marker"
    media = local_media_from_library_item(item)
    assert "secret" not in str(media.provenance)
    assert "private-marker" not in str(media.provenance)
