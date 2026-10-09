# International user trade visibility and access audit

International scope: all currently broker-supported countries, as requested.

## Implemented repair

The authenticated consumer API and gateway had empty placeholder trade-history
responses. The API also hardcoded trading_enabled=true and engine_status=running;
the gateway treated an in-process control status as execution readiness.

Both API/gateway history routes now read canonical confirmed closed trades for the identity
in the existing JWT. A mismatched user_id query returns 403. The customer reporter
rejects missing/platform identity, binds every SQL query to the same user and
position, and requires unambiguous broker/order close evidence. Raw notes,
other users' transactions, manual closes and inconsistent fees are not exposed.

GET /api/trading/history supports limit (1..200), offset (0..100000), optional
broker (kraken/coinbase/okx/alpaca), and an IANA timezone such as Europe/London or
Asia/Tokyo. UTC timestamps are retained alongside local timestamps with offsets.
Pagination advances over excluded records and reports next_offset and has_more.
Broker filtering applies within the scanned page, so an empty page can still
have more records. These records are completed positions, not pending orders or
all opening fills. Historical access is independent of current trading permission.

Prices identify the symbol's quote currency (USD for Alpaca stock symbols).
P&L remains the ledger's recorded number; its currency and FX conversion are
explicitly unverified. No local-currency conversion, carrying cost calculation,
marketplace permissions or optimal-timing claims are invented.

The web customer display now loads private history in the browser IANA timezone,
uses text nodes for exchange identifiers, shows local and UTC times and order IDs,
supports older pages, clears stale records on failure/logout, and discards responses
from a previous sign-in. It displays unknown net-result units explicitly.

GET /api/trading/status (and the unified mobile status endpoint) now reports the authoritative paid/consented user's
entitlement, connected credential venues and blockers. It does not equate
entitlement or an in-memory running flag with fresh broker permission, country
eligibility or execution proof. The API is read-only; engine trading gates and
all existing entries/exits/sizing are unchanged.

## Production verification and unfinished dependencies

PR #2975 was approved and merged as 2da43f35. A later production deployment
(612f26e, PR #2977) contains the repair. /market-observerz now reports running,
with current catalogs/quotes for Kraken, Coinbase and OKX. Public quotes do not
prove a customer's access or completed trades. /readyz still returns 503 with
LIVE_PENDING_CONFIRMATION despite reconciliation and position sync reporting
ready. Live international execution is therefore not certified.

The selected Render workspace contains the trading bot, a billing API/staging
API and a worker. No deployed authenticated consumer API/gateway service was
identified there. The history repair is in the consumer API code and requires
that authenticated service to be deployed with access to the canonical ledger,
existing JWT/ToS enforcement and durable per-user state. Never publicly mount the
unauthenticated operator dashboard as a substitute. Do not copy a platform ledger
or one user's credentials to all customers. Other workspaces/services may exist;
they were not silently assumed to be the production customer API.

Required international rollout evidence:
- For each customer's verified broker account: current country/residence/entity,
  account approval, product/asset permissions, funding, trade API authority and
  short/margin/derivative eligibility where applicable.
- Account-scoped execution readiness plus protected entry/exit and confirmed fill
  reconciliation. NIJA cannot make unsupported countries or products available.
- End-to-end UI requests using each user's own token; private live history from
  the runtime's canonical ledger, not a separate empty container database.
- Tested API deployment and customer display before claiming visible live trades.

## Primary broker sources checked October 8, 2026 (Pacific)

- Kraken licensing/region services: https://support.kraken.com/articles/where-is-kraken-licensed-or-regulated
- Kraken margin eligibility: https://support.kraken.com/articles/4402532394260-client-eligibility-for-margin-trading-services-
- Coinbase country/transaction support: https://help.coinbase.com/coinbase/trading-and-funding
- Coinbase International Exchange (separate institutional product): https://www.coinbase.com/international-exchange
- OKX residence changes and account/data-center implications: https://www.okx.com/help/what-do-i-need-to-do-when-i-change-my-country-of-residence
- Alpaca available countries: https://alpaca.markets/support/countries-alpaca-is-available
- Alpaca live-account onboarding: https://docs.alpaca.markets/us/docs/account-plans

Broker support varies by account, region and product; no static universal
country allowlist is asserted by this patch. It does not bypass any restriction.

## Validation

Nine local Python tests and three JavaScript display tests (including route/auth checks on both actual consumer route
functions) cover owner separation, authenticated/unauthenticated requests,
invalid query parameters, London/Tokyo timestamps, fee consistency, ambiguous
close proof and unverified entitlement. AST-isolated route tests avoid starting
production managers; they do not prove deployed API/JWT/store configuration or
ToS integration. The CI workflow now runs these regressions explicitly. Production Python 3.11
and full CI remain release requirements. Dedicated runtime-tools-secret_scanning
and codeql_checker tools were not available; equivalent detect-secrets CLI and
GitHub CodeQL CLI checks were run locally. No new secret findings; two unchanged
API example/component labels were reviewed as keyword false positives. CodeQL
SQL/command injection queries found zero alerts in the four changed runtime
Python files. This focused analysis is not a full repository security audit.

Full CI initially found one unexpected existing writer-lease callback test
failure (2494 tests, 168 known failures). Its current-owner fixture did not pin
owner identity when a newer process-global lineage was left by earlier tests.
The callback test now pins exact ownership, matching adjacent current-owner
fixtures. Separate stale-runtime tests continue to verify callback suppression
and preservation of newer authority. No writer production code or failure
baseline was changed. The 32 writer-lease tests also passed locally.

## Frontend integration follow-up

Review identified that fastapi_backend.py serves this same frontend. Its
/api/trading/history and /api/trading/status routes were absent, so Flask-only
repairs did not connect that frontend. FastAPI now has authenticated canonical
history plus readiness status at both /api/status and /api/trading/status.
Tests exercise actual FastAPI JWT/rate-limit dependencies through an ASGI client,
including owner separation, Tokyo timestamps, both status aliases and sanitized
errors. They isolate startup managers, so deployed stores/JWT configuration
remain unverified.

Alpaca hyphenated stock symbols now report USD before crypto quote parsing.
Entitlement evaluation excludes live-mode/credential prerequisites while account
execution remains unverified. Flask/gateway validation failures return generic
messages; gateway/mobile docstrings describe the actual readiness contract.
These changes require a new CI run on the updated head, not prior CI results.

Follow-up validation: 12 international Python tests, 32 writer-lease tests,
and three JavaScript tests passed locally. Focused CodeQL SQL/command-injection
queries report zero alerts; the exception-exposure query reports existing alerts
in untouched handlers and none on changed lines. The two reviewed history
exception exposures are removed. This is not a full application security audit.
