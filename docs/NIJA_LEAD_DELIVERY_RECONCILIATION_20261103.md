# NIJA website lead delivery: certified facts and gated recovery

Status: **NOT END-TO-END CERTIFIED. DO NOT BULK REPLAY OR REDEPLOY ONLY FOR DIAGNOSIS.**

## Evidence collected from the authenticated existing Render production Shell (2026-11-03)
- Workspace `Nija_Trading_Bot`, service `srv-d98dsr5aeets73fpbaqg`.
- `/app/data` is a symlink and `/app/data/nija_outreach.sqlite3` and
  `/data/nija_outreach.sqlite3` identify the **same underlying file**.
- `/data` persistent disk mounted, active lead DB and forwarding DB exist.
- Aggregate snapshot: 87 website lead events, 82 distinct normalized emails,
  12 forwarding rows all `pending`, 86 CRM mirror events `synced`,
  1 CRM mirror event `needs_review` categorized `HTTP_422_email`.
- Last local lead `received_at`: `2026-10-20T12:23:04.867Z`.
- `NIJA_LEAD_FORWARD_URL` absent. Intake authentication variable present.
- Independent Apollo `NIJA Website Leads` list had 23 unique contacts at prior lookup;
  other NIJA lists exist and overlap. **86 local synced events are not independently
  86 distinct Apollo contacts**.
- IONOS LIVE website form save/readback inconsistency remains unresolved.
- Render account shows a payment-failed banner; address via billing review.
- All counts above are *snapshots*, not a consistent backup, not conversion
  attribution, and not proof that Zapier or Apollo processed all events.

## Proposed read-only tool in this PR
`scripts/nija_lead_delivery_reconciliation_readonly.py` summarizes the
existing databases using SQLite `mode=ro&immutable=1` only when there are no
WAL/SHM sidecars and the header does not indicate WAL mode. It prints
whitelisted aggregate counts and error categories, never emails, webhook URLs,
provider responses, tokens or event IDs. It does not replay, delete, migrate,
repair, create a snapshot, contact Apollo, or authorize trading.

`.dockerignore` is amended so the new tool and the prior storage diagnostic
are available in future reviewed images. CI tests are offline with synthetic
fixtures only.

**Do not merge solely to make the script available:** the production service
automatically deploys release-branch changes. The database paths are mounted,
but rollback, backup, billing status and production impact still need review.

## Release and reconciliation gates
1. Confirm the actual deployed instance, current source SHA, disk, and an
   independently verified consistent database backup/restore procedure.
2. Confirm IONOS published forms save and the authenticated admin can read back
   the same durable LIVE entry. Do not publish an unverified draft.
3. Verify authorized Zapier business account `28290328`, Zap `378270777`,
   active plan/task history and the exact private Catch Hook **in the provider
   UI**. Do not expose the hook in chat or logs. A hostname check does not
   prove ownership, Zap identity, provider receipt or correct downstream mapping.
4. Only after a validated destination, configure the protected
   `NIJA_LEAD_FORWARD_URL` by an authorized, reviewed environment change.
   Render env modifications can trigger a production restart/deploy.
5. Once intake integration is verified, submit **one** internal consent-aware
   test event through the published site, verify durable storage, HTTP 201,
   exact replay HTTP 200 without duplicate notification, and check Zapier
   task receipt plus Apollo contact. Never use a trading order as a lead test.
6. Hold the single `HTTP_422_email` row for source-data review. Do not print
   personal information, auto-correct an address, or requeue a rejected record
   absent validated correction and consent.
7. For the 12 pending notification-history rows, match event IDs one by one
   against IONOS and Zapier receipts and previous messages. The current
   `_claim_forward` state and lease protect local dedupe but cannot prove
   exactly-once delivery when a provider response was ambiguous. A bulk
   re-send may duplicate customer email. Do not replay before independently
   reconciling and recording explicit owner approval.
8. Validate Apollo's normalized email identities and existing contacts across
   overlapping NIJA lists; never conclude every `synced` event means a new
   distinct contact or an actual sale.
9. Resolve Render's payment-failure alert to protect service availability.
10. Maintain all existing kill-switch, exchange, ledger, opt-out, payment,
    billing and calling restrictions. No production trading changes.

## Current disposition
Only offline tests and a review branch have been created. **Production
forwarding is not enabled and historical records have not been replayed.**
