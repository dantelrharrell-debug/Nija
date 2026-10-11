# Dante and NIJA account-separation preparation

The current accounts in the `platform` runtime role belong to Dante, as declared
by the operator. This is an ownership declaration, not brokerage verification.
The legacy execution and ledger identifier must remain `platform` until the
existing records and open orders can be migrated safely.

## Prepared state

After review and deployment, set `NIJA_ACCOUNT_OWNERSHIP_MODE=dante_personal`
to display the existing account as **Dante — Master User** in the account layer
and user dashboard metadata. Existing account keys, trading authority, risk
limits, orders, positions, and P&L queries retain their identifiers.

Four separate **NIJA — AI Platform** business profiles appear disabled:
Kraken, Coinbase, OKX, and Alpaca. They have no execution identity, balances,
or broker client. Brokerage execution identity and administrator login identity
remain separate concepts; the legacy `platform` key is not an administrator login.

## Dante's owner and administrator authority

Only the enabled login account whose exact ID is pinned in `NIJA_OWNER_USER_ID`
is the creator, master user, and owner. A person registering with the display name
"Dante", a login ID named `platform`, a brokerage API key, a subscription tier,
or a token containing a client-supplied role never establishes owner authority.

All other login accounts start without administrator privileges. Dante alone
can grant or revoke administrator access. A delegated administrator can operate
protected controls but cannot create more administrators, revoke Dante, or
transfer ownership. Ordinary users can still use existing personal-service APIs;
the user dashboard's read-only P&L/risk/nonce requests are restricted to their own
login IDs. Cross-account reports and dashboard mutations require administrator
authority. The old personal `platform` records are available to Dante and his
explicitly delegated administrators.

The following authenticated endpoints share one durable permission policy in
the Flask gateways/dashboards and FastAPI gateways:

| Endpoint | Permission |
|---|---|
| `GET /api/admin/me` | Active authenticated login; returns server-calculated role |
| `POST /api/admin/grants/{login_user_id}` | Dante only; grant administrator access |
| `DELETE /api/admin/grants/{login_user_id}` | Dante only; revoke administrator access |

Grants and revocations are recorded atomically in a separate permission database
with an audit history. Revocation is checked on every protected request, even for
already-issued tokens. Disabled login accounts are denied. Disabling the owner
invalidates delegated authority. Permission-storage errors fail closed. Changing
the owner binding is an operator action, not an API operation; old grants do not
carry across that change.

The owner dashboard now signs in through the existing NIJA login endpoint and
keeps its token in memory only. Only Dante sees grant/revoke controls. Server
authorization remains mandatory even if another user manually calls the routes.
Expired or revoked sessions clear dashboard data by reloading. Root-directory
static-file serving is disabled so database and source files cannot be downloaded.

## Deployment prerequisites — verify before merging or activating

- Verify Dante's existing login with its authenticated database record, then pin
  that record's exact `user_id` as `NIJA_OWNER_USER_ID`. Never infer a login ID from
  this document, the display name, the email prefix, or `platform`.
- Set `NIJA_AUTH_USER_DB_PATH` to the existing login database on verified durable
  storage, shared with the relevant API processes. The login singleton and
  administrator validator now use the same configured path. Back up that database
  before applying configuration. Do not point it at the trading ledger.
- Set `NIJA_ADMIN_DB_PATH` on persistent storage; its directory must already
  exist. By default the permissions database lives alongside the login database.
- Configure the same strong `JWT_SECRET_KEY` used by the existing login issuer.
  Administrator access accepts expiring HS256 login tokens only and checks the
  current login record. A missing signing key does not fall back to a random key.
- Set `NIJA_OWNER_LOGIN_URL` on the owner-dashboard service to the existing HTTPS
  `/api/auth/login` endpoint. Its CORS configuration must permit the owner
  dashboard's exact origin. Configure a nondefault owner PIN for the additional
  existing PIN checks; an absent fallback PIN is denied.
- Set `NIJA_ACCOUNT_OWNERSHIP_MODE=dante_personal` after the status changes are
  deployed and reviewed. Verify the UI identifies Dante, ordinary users are
  denied control endpoints, and a controlled grant/revoke works after restart.
- Complete CI, CodeQL, security review and operator identity binding before
  deployment. This PR does not remotely set these values or manufacture an owner
  record. Missing configuration deliberately denies access.

This secures the named API/dashboard administrator surfaces, not OS, GitHub,
Render workspace permissions, or every alternate/archived API implementation.
Deploy only the supported gateways with this policy; do not expose an older
dashboard implementation as a parallel route around it.

Future business credentials use a separate namespace:

| Exchange | Dedicated prefix |
|---|---|
| Kraken | `KRAKEN_NIJA_BUSINESS` |
| Coinbase | `COINBASE_NIJA_BUSINESS` |
| OKX | `OKX_NIJA_BUSINESS` |
| Alpaca | `ALPACA_NIJA_BUSINESS` |

Each prefix has `_API_KEY` and `_API_SECRET`; OKX also has `_PASSPHRASE`.
The staged reader never uses legacy personal keys or fills incomplete business
credentials from another namespace. Exact API-key reuse is rejected. Different
keys for the same broker account still require account-ID checks.

**Adding these keys does not connect or enable a business account yet.** This PR
prepares labels and isolated credential slots; it does not implement a complete
execution migration. Other dashboards and aggregate reports may still use the
legacy platform terminology. Do not substitute business keys into existing
`*_PLATFORM_*` or bare exchange variables while personal positions remain there.

## Required migration before business trading

1. Approve the business brokerage account and independently verify its legal
   owner, authenticated account ID, API permissions, and supported API format.
2. Compare account IDs across all connections, rejecting duplicate accounts
   even when API keys differ. Never log credentials.
3. Pause new entries for the affected personal brokerage while keeping its
   protective exits operational. Take and verify an online database backup.
4. Reconcile personal fills, fees, open positions, and pending orders. Map the
   old `platform` records to Dante per brokerage, preserving IDs and history.
5. Review and test account-scoped client loading, storage, order routing,
   protection, risk state, and P&L. Existing platform-readiness dependencies
   must be audited without weakening authority or capital gates.
6. Activate one business account at a time only after the migration and
   existing live-trading gates pass. Confirm personal exit continuity and
   distinct account balances before resuming entries.

This preparation does not move money, change legal account ownership, or
resolve the existing Kraken reconciliation and execution-readiness blockers.
