# OKX Independent Connection and Trading Guide

This guide supplements `README.md`. The README currently documents Coinbase in detail but does not yet contain an equivalent OKX production section.

## Isolation contract

OKX is an optional, broker-local venue. An OKX authentication, balance, funding-wallet, symbol, minimum-order, or order-submission failure must:

- disable or quarantine OKX entries only;
- leave Coinbase and Kraken connected and tradeable;
- leave global execution authority unchanged when at least one healthy broker remains;
- preserve OKX exit handling when authenticated access is available;
- never fall back between regional OKX domains after a signed request fails.

## Required production variables

Use one matching credential set created in the same OKX account and environment:

```bash
OKX_API_KEY=...
OKX_API_SECRET=...
OKX_API_PASSPHRASE=...
OKX_ACCOUNT_REGION=US
OKX_BASE_URL=https://us.okx.com
OKX_SIMULATED_TRADING=false
OKX_USE_TESTNET=false
```

Regional hosts:

- United States account: `https://us.okx.com`
- EEA account: `https://eea.okx.com`
- Global account: `https://www.okx.com`

Do not mix a key created on one regional account with another region's host. Do not configure multiple conflicting OKX credential aliases.

## API-key permissions

The key must have:

- Read permission for balances, account configuration, instruments, orders, and fills.
- Trade permission for placing, canceling, and closing orders.
- No withdrawal permission.

When IP restrictions are enabled, allowlist only the backend's stable outbound IP. A normal dynamic Render or Railway egress address is not suitable for a strict allowlist unless static egress is configured.

## Spot order contract

NIJA submits OKX spot orders to:

```text
POST /api/v5/trade/order
```

Required order fields:

```json
{
  "instId": "BTC-USDT",
  "tdMode": "cash",
  "side": "buy",
  "ordType": "market",
  "sz": "25",
  "tgtCcy": "quote_ccy"
}
```

For a market sell, `sz` is base-currency quantity and `tgtCcy` should be `base_ccy` or omitted when the OKX default is appropriate.

## Authentication recovery

Run from a secure deployment shell:

```bash
python scripts/diagnose_okx_auth.py
```

Interpretation:

- `50110`: deployment IP is not allowed.
- `50111`: invalid key, disabled/deleted key, wrong environment, or wrong regional host.
- `50112`: passphrase does not match the exact key.
- `50113`: secret/signature/request-path mismatch.
- `50119`: key does not exist on the selected regional host.

After replacing credentials, perform a full redeploy. The process-local quarantine intentionally remains latched until restart so a rejected key is not retried continuously.

## Expected healthy evidence

```text
OKX_REGIONAL_ENDPOINT_SELECTED ... broker_scope=okx_only
OKX auth diagnostic passed
OKX funding/trading wallet observed
NIJA_OKX_CONNECTED=1
NIJA_OKX_TRADING_READY=1
NIJA_OKX_ACTIVATION_STATE=ready
```

A healthy deployment must also continue to report Coinbase and Kraken readiness independently when OKX is unavailable.
