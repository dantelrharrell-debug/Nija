# Authenticated Kraken balance evidence

The production collector lacks independently bound producers for all required
checks. The existing v477/v480 providers cover key permissions and identity.
`bot.kraken_authenticated_balance_provider.make_kraken_balance_provider` supplies
the separate `broker_balances` observation for a reviewed default-wallet mapping.

The factory takes the existing direct, nonce-owning Kraken client, exact account
scope, independently approved account IIBAN/API-key SHA-256 pins, reviewed
provider ID, and the canonical monitoring category. Pin/account/wallet mapping
review is required; never learn approved pins from the response being certified.

It reads `GetApiKeyInfo`, `BalanceEx`, then `GetApiKeyInfo` through the same
existing private-call boundary. The transport key, account identity, connection
scope and 60-second observation lifetime must remain valid. Gateway mode is
unsupported and fails closed. It creates no client, nonce owner, network
listener, request file, order, ledger update, or activation flag.

Kraken documents BalanceEx as a non-paginated default-wallet asset map. Empty
maps are valid balances but cannot prove an empty or reconciled ledger. Asset
variants such as `USDT` and `USDT.F` remain distinct. Unknown/incomplete fields,
non-finite/negative amounts and negative available balances fail closed. The
credit pair is optional only when both fields are absent. No USD conversion or
capital sufficiency claim is made. Observation output contains a digest rather
than asset quantities, account identifiers, credentials or approved pins.

## Production acceptance still required

Register this provider under `broker_balances` only after its code, actual client,
scope, pins and default-wallet mapping have been independently reviewed. The
existing collector still requires every other v452 provider and its trusted
source binding. This module does not auto-install or call order admission.

Ledger/opening-lot reconstruction, order and fill reconciliation, protective
exits, duplicate fence, writer lease, nonce ownership, operator authorization,
kill switch, risk state and position sync remain separate prerequisites. Current
production installation and successful certification have not been established.
Use the existing controller for any activation decision.

## Offline validation

`NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -S -B -m unittest discover -s tests -p test_kraken_authenticated_balance_provider.py -v`

These synthetic tests exercise refusal behavior and the single-field v452
contract. They do not prove production credentials, balances or trading readiness.

Official sources:

- https://docs.kraken.com/api-reference/account-data/get-extended-balance
- https://docs.kraken.com/api-reference/account-data/get-api-key-info
- https://render.com/docs/deploys

Render supports deliberate deployment of a specific reviewed Git revision, so a
collector can ultimately be installed through normal runtime code integration.
A shell is not the only possible installation route. A redeploy does not itself
provide missing evidence producers, independent bindings or certification.
