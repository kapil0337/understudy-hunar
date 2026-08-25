# Channel strategy: voice first, messaging on no-answer

## Voice is the depth channel, messaging is the reach channel

A voice call from an agent gets through a full structured screen — every knockout question
asked, an objective yes/no on qualification, in one conversation. That depth is exactly what
frontline hiring needs: the roles have no resume to fall back on, so the screen itself has to
carry the signal. Voice is expensive per attempt (a ringing call ties up a Hunar line and minutes
whether or not it connects) and it is intrusive — a phone ringing demands the candidate's
attention right now.

WhatsApp cannot carry that same screen inside Meta's messaging rules (see below), but it costs
close to nothing per attempt, tolerates being ignored, and lands even when a candidate is mid-
shift or in a signal-dead spot. It cannot ask five screening questions and extract a structured
result the way a call can. So it is the reach channel: its job is to get a candidate who did not
pick up back onto a phone call, not to replace one.

## Sequencing policy

1. Voice first, always. Every candidate's first outreach attempt is a call.
2. On `NOT_CONNECTED`, retry by voice per the job's `retry_config` (up to `max_retry_count`
   attempts, spaced `retry_interval_hours` apart).
3. Only after retries are exhausted and the candidate is still `NOT_CONNECTED` does messaging
   fire — a WhatsApp nudge asking them to call back or confirm a better time.
4. A reply on WhatsApp does not replace the screen. It reschedules a voice attempt. The
   screening call still has to happen for the result to be usable.

Messaging never fires ahead of voice, and never substitutes for it — it exists purely to convert
a `NOT_CONNECTED` into another chance at a real call.

## Why this ordering lowers cost per qualified candidate

At frontline hiring volume — hundreds of leads per role, most of whom will not qualify or will
not answer — the expensive step (a real ringing call, with an agent's minutes and a phone line
behind it) has to be spent on candidates likely to actually pick up. Calling every lead by voice
first and repeatedly is what the retry budget is for; but once that budget is spent on someone
unreachable, paying for more calls to the same dead number is waste. A near-free WhatsApp nudge
is cheap enough to send to everyone still unreached, and it only has to convert a small fraction
of them back into an answered call to pay for itself many times over. Cost per *qualified*
candidate falls because the calls that do connect are increasingly concentrated on candidates who
have just signalled, by replying, that they are actually available — not spent blind on numbers
that have gone quiet.

## 24-hour window mechanics

WhatsApp Business messaging has two modes:

- **Template messages** — pre-approved by Meta, can be sent to a candidate at any time,
  including cold (no prior message from them). Required for the first outbound nudge to anyone
  who has never messaged the recruiting number.
- **Free-form (session) messages** — can only be sent within 24 hours of the candidate's last
  incoming message. Once that window closes, the only way back in is another template send.

So the real flow is: template out ("we tried to call you about the role, reply YES to get a
callback") -> candidate replies -> that reply opens a 24h window -> inside the window, free-form
messages can confirm the number and consent explicitly -> an affirmative reply inside the window
is what actually sets `phone_e164` / `consent_recorded_at`. If the candidate goes quiet again
before consent is confirmed, the window lapses and getting back in requires another template.

## Honest status: scoped out

WhatsApp is **not implemented** in this build. Three days did not leave room for a WhatsApp
Business integration (permanent System User token, an approved template, webhook handling for
inbound replies) on top of the voice path, and voice-first is where the accuracy of the screen
actually lives — that had to come first.

The seam is left in place on purpose: `app/services/consent.py` defines `ConsentChannel` as a
`Protocol` with `request_consent` / `handle_inbound`, `ManualConsentChannel` implements it today
(a recruiter enters a number and ticks a consent box), and
`app/integrations/whatsapp/channel.py` implements the same Protocol with both methods raising
`NotImplementedError` and a module docstring carrying the flow above. Building WhatsApp later
means writing that one file; nothing that depends on `ConsentChannel` needs to change.
