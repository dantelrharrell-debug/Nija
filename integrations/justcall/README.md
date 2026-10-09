# NIJA JustCall outbound integration (pre-launch)

This directory contains a **fail-closed screening policy only**. No dialer client, API calls, contact export, or production deployment is included yet.

## Segregated campaigns
- **B2B:** Business partnerships, sponsorships, and affiliates. Require validated business recipient and purpose, suppression clearance, time-zone/calling-hours verification, human-operated dialing, and timestamped screening.
- **Consumer:** Individual product offers. Require validated consent covering the specific call and dialing method, suppression clearance, permitted hours, and timestamped screening. Review all applicable federal/state requirements before launch.

## Rollout gates
1. Provision a **separate** Render integration service, not the live trading bot or billing API.
2. Store JUSTCALL_API_KEY and JUSTCALL_API_SECRET as Render secret environment variables; never commit or print them.
3. Implement authenticated JustCall client using current vendor documentation, bounded retries, rate limits, redacted logs, and no automated outbound calls by default.
4. Establish verified Apollo contact mapping, per-number provenance, consent evidence, business-purpose classification, DNC/opt-out suppression, and local calling hours.
5. Run unit tests, integration tests against sandbox/test contacts, and verify JustCall event logging and opt-out propagation.
6. Launch a small supervised human-operated pilot with written compliance approval, then scale based on capacity and compliant lead supply.

**Hard stop:** Never infer permission to call from an email verification, website form submission, employer title, or presence of a headquarters phone number. Do not dial unless eligibility passes. No AI prerecorded calls.
