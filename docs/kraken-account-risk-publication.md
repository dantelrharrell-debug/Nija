# Account risk publication implementation

`ReviewedAccountRiskPublisher` supplies atomic publication and the real
`read_snapshot(account, api_key_sha256)` API consumed by the existing native
risk reader. Its canonical-constructor regression exercises that exact path.
No production hook or instance is installed by importing this module.

The publisher accepts the complete account-specific envelope already required
by `kraken_risk_evidence.py`. It preserves capital, exposure and policy values,
their source identities and original observation/expiry times. It runs the
existing full risk validator rather than a second, less restrictive version.
Publication is all-or-nothing under a process lock. Reads return detached copies.

Every publication and read authenticates the exact current snapshot against
its reviewed owner before and after validation. Revocation, owner mutation,
reentrant invalidation, a bad replacement, or expiry withdraws the publication.
There is no fallback to the last healthy value. Envelope revisions increase;
record revisions cannot decrease or be reused for different data. Authenticated
blocked states consume their revisions even when the risk reader rejects them.
Restart begins empty, with a separately provisioned exclusive revision floor.

## Actual production dependencies

This implements publication, not the missing source measurements. The protected
root must supply an authentic `authenticate_current` implementation covering
the actual canonical capital, complete exposure (including pending obligations),
and account policy owners. It must verify current data and revisions on every
call, including all intervening and reverted changes. Comparing a caller's own
flags, using a blanket True callback, or substituting global risk statistics
does not meet this contract. These callbacks run as trusted code and require
review of the actual owners and mutation coverage.

On every account change/disconnect/halt the owner must synchronously call
`invalidate`; the authenticator must independently detect changes if that hook
fails. A fresh complete authenticated snapshot with advancing revisions can
then be published. Do not re-date old measurements or replay an old revision.

The object can be supplied as `ReviewedRiskSource.source` in the existing native
four-source binding after that binding is genuinely reviewed. Actual live
account measurements, revision ownership, protected source provisioning,
startup receipts, full ledger reconciliation and release/security approval
remain required. This change supplies none of those approvals or measurements.
It performs no broker calls, creates no signing keys, changes no production
settings, and grants no order authority.

## Verification

Offline tests cover the actual native risk reader and canonical constructor,
mutation isolation, stale timestamps, invalid scope/provenance/protection,
halts, revocation during a read, invalid replacements, rollback/reuse,
restart floors, reentrant invalidation and concurrent publication/read.
Synthetic test owners are not production review evidence. Hosted Python 3.11
checks and independent review are required before merging this component.
