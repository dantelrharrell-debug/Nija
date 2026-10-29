# Explicit cursor history recovery

This change adds a read-only recovery option. It does not install the independent
certification collector or authorize execution. Existing requests retain offset
pagination when `use_cursor` is absent or false.

## Operation after review and deployment

The trusted production operator can submit a **new** private recovery request
with the existing request fields and `"use_cursor": true`. Preserve every old
claim and receipt, especially interrupted requests. Never replay a claimed ID.
Keep the existing private-directory, mode-0600 file, request age, exclusive
creation and page-budget requirements. Do not submit a request from an isolated
one-off job: the production disk and existing broker must be available.

The collector reuses the selected running broker's monitoring boundary and
nonce owner. It follows cursor tokens for TradesHistory, ClosedOrders and
Ledgers, repeats the full history read, then performs the existing open-order
and balance checks. The page budget applies separately to each endpoint/pass.
It does not retry or fall back to offset mode on an error. Kraken's history
requests consume weighted rate-limit capacity; the existing client's limiter
must remain in control. This change adds no private-client process or sleep loop.

An explicit cursor object is required on every historical page. An empty object,
null `next`, or empty-string `next` indicates termination; a missing or malformed
cursor envelope fails closed. If production returns a different terminal shape,
retain the failed receipt and review a sanitized response shape before changing
the parser. No private response contents are logged by this change.

Cursor exhaustion and repeat consistency are not an atomic brokerage snapshot,
independent identity proof, ledger certification, or protective-exit coverage.
All existing evidence denials remain false.

## Remaining production dependencies

1. Restore supported access to the running Render service. CLI login succeeded
   in the recovery session, but SSH failed resolving the regional hostname.
   SSH also requires a registered public key. Dashboard Web Shell is a separate
   supported route. Do not deploy/restart to repair operator access.
2. Invoke the existing reviewed GetApiKeyInfo providers through the live client
   and compare with independently approved account/key pins. Never derive pins
   from that same response, commit them here, or print credential values.
3. Collect complete authenticated history and reconcile actual ledger links and
   protective orders. Preserve unresolved records; never synthesize opening
   intents or strategy ownership from exchange fills alone.
4. Complete and independently review every missing authority producer. The
   reviewed v483 bundle intentionally covers only four of thirteen fields.
   Runtime flags cannot substitute for writer, nonce, operator, or risk evidence.
5. Install the certification collector only after complete producer validation,
   then rerun current certification. These offline tests are not live proof.

## References checked October 28, 2026

- https://docs.kraken.com/api-reference/account-data/get-trades-history
- https://docs.kraken.com/api-reference/account-data/get-closed-orders
- https://docs.kraken.com/api-reference/account-data/get-ledgers-info
- https://docs.kraken.com/api-reference/account-data/get-api-key-info
- https://support.kraken.com/articles/206548367-what-are-the-api-rate-limits-
- https://render.com/docs/ssh
- https://render.com/docs/one-off-jobs

## Validation and review

The targeted recovery, identity and reconciliation suite passed 121 tests locally
on Python 3.12. The workflow repeats it on production's Python 3.11. A pre-existing
literal-newline syntax error in the reconciliation test was corrected so its
uncertified-readback denial actually runs.

The requested runtime-tools-secret_scanning and codeql_checker interfaces are
not available in this environment. Use the repository's Gitleaks and CodeQL CI
checks and require human review before merge, as directed by AGENTS.md. Do not
treat local validation as a passing CI or production certification result.
