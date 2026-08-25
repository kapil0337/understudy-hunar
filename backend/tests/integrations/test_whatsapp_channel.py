from __future__ import annotations

import uuid

import pytest

from app.integrations.whatsapp.channel import WhatsAppConsentChannel
from app.models.candidate import Candidate
from app.models.job import Job


async def test_request_consent_not_implemented() -> None:
    channel = WhatsAppConsentChannel()
    job = Job(title="x", raw_jd="raw")
    candidate = Candidate(
        job_id=uuid.uuid4(),
        source_provider="fixtures",
        source_ref="fx_001",
        full_name="Test Candidate",
        skills=[],
        raw_payload={},
    )

    with pytest.raises(NotImplementedError):
        await channel.request_consent(candidate, job)


async def test_handle_inbound_not_implemented() -> None:
    channel = WhatsAppConsentChannel()
    with pytest.raises(NotImplementedError):
        await channel.handle_inbound({})
