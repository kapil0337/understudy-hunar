"""WhatsApp consent channel — NOT IMPLEMENTED. Scoped out of the three-day build; this module
exists to leave the seam in place so it can be added later without touching anything else that
depends on the ConsentChannel Protocol (app/services/consent.py). See docs/channel-strategy.md
for why messaging is the reach channel and voice is the depth channel.

The full flow, when this is built:

  1. Outbound (request_consent): send an approved WhatsApp Business "utility" template message
     to the candidate's number. A template is mandatory here — Meta's messaging policy forbids
     free-form messages to a user outside an active 24h service window, so the very first
     message to someone who has never messaged us has to be a pre-approved template.

  2. The candidate's reply opens a 24h service window (WhatsApp's rule: any user-initiated
     message re-opens free-form messaging for 24h from that message's timestamp). Everything
     after this point must happen inside that window, or drop back to another template send.

  3. Inside the window, send a free-form message that restates the candidate's number back to
     them and asks them to confirm both the number and their consent to be called about the job.

  4. handle_inbound processes their reply:
       - Affirmative -> sets phone_e164 and consent_recorded_at (channel=WHATSAPP), i.e. calls
         app.services.consent.record_consent(..., channel="WHATSAPP").
       - Negative -> sets dnc=True, i.e. calls app.services.consent.record_decline(...).
       - Anything else -> ConsentOutcome(outcome="pending"); no candidate field changes, and the
         window may need re-confirming once it re-opens.

  5. Requires a permanent WhatsApp Business "System User" access token (a user token expires;
     the whole point of consent tracking is that it keeps working unattended) and at least one
     Meta-approved utility template before step 1 can ever fire.

CHANNEL env var selects the implementation (manual | whatsapp); default is manual — see
app/services/consent.build_consent_channel.
"""

from __future__ import annotations

from typing import Any

from app.models.candidate import Candidate
from app.models.job import Job
from app.services.consent import ConsentOutcome, ConsentRequest


class WhatsAppConsentChannel:
    name = "WHATSAPP"

    async def request_consent(self, candidate: Candidate, job: Job) -> ConsentRequest:
        raise NotImplementedError(
            "WhatsApp consent channel is not implemented — see this module's docstring for the "
            "designed flow and docs/channel-strategy.md for why it was scoped out."
        )

    async def handle_inbound(self, payload: dict[str, Any]) -> ConsentOutcome:
        raise NotImplementedError(
            "WhatsApp consent channel is not implemented — see this module's docstring for the "
            "designed flow and docs/channel-strategy.md for why it was scoped out."
        )
