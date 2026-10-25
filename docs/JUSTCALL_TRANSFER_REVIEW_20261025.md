# JustCall transfer and call-event review — October 25, 2026

Related: https://github.com/dantelrharrell-debug/Nija/issues/3324

## Scope

Issue #3324 records a disabled worker, zero eligible Apollo contacts, and no
certified staffed handoff. This review uses repository source, public provider
documentation and offline mocks. It does not certify deployed configuration,
provider entitlement, consent records, staffing, or real call outcomes.
Private correspondence and support-case details are excluded from this report.

## Supported corrections

- Require the explicit documented `v1` signature version and bind the signed
  webhook URL to NIJA's configured receiver. A valid MAC for another receiver is
  no longer accepted. Keep constant-time HMAC comparison and reject before
  persistence/suppression side effects.
- Reject failed/error envelopes at every inspected voice-agent response level.
  Bind provider transfer evidence to the requested call ID/SID. Same-agent data
  from a different call is insufficient. Continue to require successful action,
  warm mode and the boolean `is_answered: true`.
- Register the existing `call.missed` and `call.voicemail` handlers through the
  idempotent webhook-registration path. These events describe missed incoming
  calls/voicemails; they do not independently prove an outbound transfer's
  no-answer fallback. Existing persistence deduplicates request IDs. No retry,
  callback, SMS, or calling action is added.
- Run focused offline regressions in the handoff workflow with dialing and
  human-handoff flags disabled.

The current API reference documents `/calls/{id}/voice-agent`, which is already
used. An older Help Center article shows `/calls/voice_agent/{id}`. No endpoint
change is justified by this disagreement.

## Provider protocol limits and evidence requirements

The documented v1 MAC uses API secret, encoded webhook URL, event type and
timestamp. It does **not** include `data` or `request_id`. Signature validation
therefore does not establish event-body integrity, receiving-human identity,
or independent certification. Duplicate request-ID persistence is also not
complete protection against an altered request ID with a replayed signature.
The provider's timestamp example lacks a timezone and its call-event table
labels the timestamp as an integer. A supported timestamp format, timezone,
delivery/retry window and stronger body-authentication mechanism should be
confirmed with Solutions before defining a freshness rejection policy.

Do not use webhook-derived claims or the agent inventory to set
`NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED` or authorize dialing. The read-only audit
corroborates its limited transfer diagnostic through authenticated provider GETs;
it never changes that flag. It still requires provider confirmation that the
observed action fields represent an answered/bridged transfer. A voicemail or
another AI can answer; `is_answered` is not human-identity evidence.

## Remaining dependencies

| Requirement | Who/evidence is needed |
| --- | --- |
| Paid pilot provisioning, billing start, outbound AIVA API entitlement | Written JustCall confirmation for NIJA's actual account and selected agent |
| Usage cap, overage controls and usage accounting | JustCall confirms enforceable limit and metering; no inference from plan approval |
| Staffed warm action | Solutions confirms outbound-agent support, selects an actual Team Member or User Group, defines staffing and saves the warm routing/summary configuration |
| No-answer/busy/off-hours fallback | Provider and operator configure the intended behavior; no unattended redial/SMS assumed authorized |
| Signed-event protocol | Solutions confirms timestamp/retry semantics, payload authentication and authentic action/journey fields |
| Answered human and no-answer acceptance | Separate authorization for supervised tests, real provider call IDs, call journey, identified receiving human, summary/bridge observation, no-answer outcome and independent reviewer |
| Recipient eligibility | Authentic consent receipts, DNC review, suppression/withdrawal persistence and recipient jurisdiction/timezone evidence; existing Apollo records remain ineligible absent evidence |
| Campaign activation | Separate explicit calling authorization after all operational acceptance evidence passes |

JustCall's warm-transfer guide describes Team Member/User Group routing with
the caller held while the receiving party hears the summary. The guide also
mentions Front Desk availability; Solutions must confirm the behavior for this
specific outbound AIVA account rather than infer it from generic documentation.
No arbitrary phone number or intended closer is invented by this change.

## Sources

- https://developer.justcall.io/docs/dynamic-webhook-signatures
- https://developer.justcall.io/docs/call-events
- https://developer.justcall.io/docs/justcall-voice-agent-data-object
- https://developer.justcall.io/reference/call_get_voice_agent_v21
- https://help.justcall.io/en/articles/10903546-cold-warm-transfers-in-ai-voice-agent
- https://help.justcall.io/en/articles/11196775-how-to-log-ai-voice-agent-calls-into-any-crm-or-helpdesk-using-apis

## Validation

All JustCall test modules: **92 passed, 3 subtests passed** locally on Python
3.12. Syntax compilation and `git diff --check` passed. The full baseline suite
had one existing thread-mock isolation failure, independently reproduced on
unchanged `main`; the test now mocks both read-only audit starters explicitly.
The targeted CI workflow runs on Python 3.11.

`detect-secrets` found no secrets in changed files. Bandit found one pre-existing
`urllib.request.urlopen` B310 warning in the webhook-registration transport;
that transport was not changed. The repository-named
`runtime-tools-secret_scanning` and `codeql_checker` tools were unavailable in
this environment; these are not claimed as passed. Remote CI/security checks
and human review remain required before merging.

## Release boundary

Review only. No merge, deploy, restart, calls, test calls, campaign activation,
consent approvals, suppression removal, provider purchase changes, or trading
changes. Recipient-specific consent, DNC screening, suppression, local calling
windows and all existing outbound admission gates remain required.
