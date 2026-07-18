# NIJA AI Trading Group — Current Success State

**Status date:** July 2026

NIJA has reached a new success point: mobile-app readiness work is now connected to the live-execution protection stack and dashboard sizing workflow.

This README is the current recovery anchor for NIJA.

---

## Current Success Point

NIJA now includes:

- Broker venue cash guard.
- Position close with realized P&L calculation.
- Stop-loss and take-profit auto-exit.
- Trailing stop-loss.
- Breakeven stop-loss.
- Combo breakeven-to-trailing protection.
- Trailing take-profit.
- Combined trailing take-profit plus trailing stop-loss manager.
- Combined trailing position-size calculator.
- Dashboard trade execution panel with one-click fill.
- Mobile app blueprint for iPhone and Android development.

---

## Mobile App Blueprint Added

The NIJA mobile app blueprint has been added to this success state.

The mobile app direction is:

- Education-first user experience.
- Demo / Education Mode as the default starting point.
- Live Mode locked behind user consent and broker readiness.
- No profit guarantees.
- No investment-advice claims.
- No live trading by default.
- Broker secrets handled server-side only.
- Every user account trades independently.
- Clear risk disclosures.
- Emergency pause / kill switch required.
- Apple and Google review path defined.

---

## Mobile App Screens

The app structure is planned around five bottom tabs:

1. **Home** — account status, broker status, system status, open positions, risk state, and emergency pause.
2. **Signals** — market signal cards explaining confidence, ADX, volume, spread, fee impact, broker readiness, and why trades were approved or skipped.
3. **Trades** — completed, failed, skipped, and simulated trade history, clearly separating Education Mode and Live Mode.
4. **Risk** — daily loss limit, weekly hard stop, max position size, max leverage, minimum balance checks, disclosure history, and consent history.
5. **Profile** — user account, connected brokers, disclosures, support, privacy policy, terms, and delete account.

---

## Education Mode

Education Mode is the default experience.

It should include:

- Simulated signals.
- Simulated trades.
- Signal explanations.
- Trade pass/fail reasons.
- AI confidence score.
- Trend strength.
- Volume check.
- ADX check.
- Spread check.
- Fee impact check.
- Beginner lesson cards.

Education Mode lets users understand NIJA before using live capital.

---

## Live Mode Requirements

Live Mode must stay locked until:

- User account is created.
- Risk disclosure is accepted.
- No-financial-advice disclosure is accepted.
- Broker is connected.
- Broker balance is verified.
- Execution permissions are confirmed.
- Live trading consent is signed.
- Audit log is created.
- Emergency pause is enabled.

Live Mode should never activate automatically.

Required user confirmation:

> I understand trading involves risk and I can lose money.

---

## Broker And Security Rules

Initial broker placeholders:

- Kraken.
- Coinbase.

Rules:

- Broker API keys are never stored in the mobile frontend.
- Broker secrets are handled server-side only.
- Mobile app only talks to secure backend APIs.
- Read-only balance sync should happen before execution permissions.
- Execution requires explicit user consent.
- All live actions must create audit logs.
- Users must be able to disconnect brokers and delete their account.

---

## Connect Coinbase Correctly

NIJA connects to the Coinbase **Advanced Trade API** using a Coinbase Developer Platform secret API key. The Advanced Trade base endpoint is:

```text
https://api.coinbase.com/api/v3/brokerage
```

### 1. Create the correct Coinbase key

1. Sign in to the Coinbase Developer Platform.
2. Open **API Keys** and choose **Secret API Keys**.
3. Create a new key specifically for NIJA.
4. Under advanced settings, select **ECDSA / ES256** as the signature algorithm.
5. Enable these permissions:
   - **View** — required for balances, products, orders, fills, and permission checks.
   - **Trade** — required for buy, sell, cancel, and close orders.
6. Leave **Transfer** disabled. NIJA does not need withdrawal or external-transfer authority to trade.
7. Restrict the key to the Coinbase portfolio NIJA should trade, when applicable.
8. Save both values shown during creation:
   - API key name, formatted like `organizations/{organization_id}/apiKeys/{key_id}`.
   - EC private key, including the `BEGIN` and `END` lines.

Do not select an Ed25519 key for this Coinbase App / Advanced Trade connection. Coinbase requires ECDSA for this authentication path.

### 2. Set the production variables

Add these variables to the backend service in Railway or Render. Never place them in the mobile application or commit them to GitHub.

```bash
COINBASE_API_KEY=organizations/ORG_ID/apiKeys/KEY_ID
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
YOUR_PRIVATE_KEY_BODY
-----END EC PRIVATE KEY-----"
```

NIJA also accepts these aliases, but the canonical variables above should be used for the platform account:

```text
COINBASE_PLATFORM_API_KEY
COINBASE_PLATFORM_API_SECRET
COINBASE_CDP_API_KEY
COINBASE_CDP_API_SECRET
CDP_API_KEY_NAME
CDP_API_KEY_PRIVATE_KEY
```

Do not set conflicting values under multiple aliases. A stale `COINBASE_API_SECRET` takes precedence over later aliases and can keep Coinbase disconnected even when another alias contains a valid key.

### 3. Preserve the PEM private key

The secret must retain this structure:

```text
-----BEGIN EC PRIVATE KEY-----
base64-key-material
-----END EC PRIVATE KEY-----
```

Preferred deployment method:

- Paste the secret as a multi-line value with real line breaks.
- Do not add spaces before the `BEGIN` or `END` lines.
- Do not remove either boundary line.
- Do not paste the entire downloaded JSON file into `COINBASE_API_SECRET` unless the runtime normalization layer is intentionally being used.
- Do not wrap the value in extra quote characters in the deployment dashboard.

NIJA's authentication normalizer can repair escaped `\n` sequences and supported Coinbase JSON key payloads, but correctly formatted multi-line PEM is the safest production configuration.

### 4. Configure an IP allowlist carefully

Coinbase supports IP allowlisting. Only enable it after confirming the backend has a stable outbound IP.

- A normal Railway or Render deployment may use changing outbound addresses unless static egress is configured.
- Adding the wrong address can cause authentication failures even when the key and secret are correct.
- Never add a phone, home Wi-Fi, or mobile-app IP as the backend trading server address.

### 5. Redeploy cleanly

After changing Coinbase credentials:

1. Remove obsolete Coinbase credential variables.
2. Confirm only one key name and one matching private key are active.
3. Save the variables.
4. Redeploy the NIJA backend.
5. Do not expose or print the full private key in logs.

### 6. Verify permissions and connectivity

Run the repository credential checks from a secure backend shell:

```bash
python validate_broker_credentials.py
python validate_broker_credentials.py --test-connections
python scripts/auth_sanity.py
```

A valid key must report at least:

```text
can_view=true
can_trade=true
```

`can_transfer` is not required and should normally remain false.

The authenticated permission endpoint used by Coinbase is:

```text
GET /api/v3/brokerage/key_permissions
```

### 7. Expected NIJA startup evidence

Healthy startup should show Coinbase credential normalization followed by a successful account or balance response. Useful markers include:

```text
COINBASE_AUTH_NORMALIZED
pem_ok=True
COINBASE_CONNECTION_SUCCESS
```

The exact success wording can vary by broker adapter. The required operational result is:

```text
Coinbase connected
balance observed
can_view=true
can_trade=true
trading_ready=true
```

Never treat `COINBASE_AUTH_NORMALIZED` by itself as proof of a live connection. It only confirms that NIJA found and formatted the credential variables.

### Coinbase troubleshooting

#### `401 Unauthorized`

Check all of the following:

- The API key name begins with `organizations/` and contains `/apiKeys/`.
- The private key belongs to that exact key name.
- The key was created with ECDSA / ES256.
- The PEM includes real boundary lines and valid key material.
- No old `COINBASE_API_SECRET` is overriding a valid alias.
- The server clock is accurate because Coinbase JWTs are time-limited.
- The IP allowlist includes the backend's actual stable outbound IP, or the allowlist is removed while diagnosing.

If the private key was lost or copied incorrectly, delete the Coinbase key and create a new one. Coinbase does not provide the private key again after creation.

#### Connected but no orders can be placed

- Verify `can_trade=true` through `/api/v3/brokerage/key_permissions`.
- Confirm the key is attached to the funded portfolio.
- Confirm the available quote-currency balance meets NIJA and Coinbase minimums.
- Confirm NIJA is not in paper, dry-run, paused, quarantine, or exit-only mode.

#### Balance is missing or belongs to the wrong portfolio

Set the intended portfolio when NIJA's deployment uses portfolio routing:

```bash
COINBASE_RETAIL_PORTFOLIO_ID=YOUR_PORTFOLIO_UUID
```

Then redeploy and verify that the observed balance belongs to that portfolio before enabling execution.

---

## Apple And Google Readiness

NIJA is being structured for future release on:

- Apple App Store.
- Google Play Store.

Best launch path:

1. Phase 1 — Education app.
2. Phase 2 — Broker dashboard.
3. Phase 3 — Controlled live trading after compliance review.
4. Phase 4 — App Store and Google Play public release.

Public release is not declared complete until iOS/Android builds, store assets, privacy policy, terms, support URL, demo credentials, and financial declarations are finished and verified.

---

## Protection Stack Modules

Key modules:

```text
bot/broker_venue_cash_guard_patch.py
bot/position_close_pnl_runtime_patch.py
bot/auto_exit_sl_tp_runtime_patch.py
bot/trailing_stop_loss_runtime_patch.py
bot/breakeven_stop_loss_runtime_patch.py
bot/combo_breakeven_trailing_runtime_patch.py
bot/trailing_take_profit_runtime_patch.py
bot/combined_trailing_tp_sl_runtime_patch.py
bot/combined_trailing_position_size_calculator.py
frontend/static/js/app.js
```

Combined trailing defaults:

```bash
NIJA_COMBINED_TRAILING_TP_SL_ENABLED=true
NIJA_COMBINED_TRAILING_POLL_SECONDS=5
NIJA_COMBINED_TRAILING_SL_ACTIVATION_PCT=0.003
NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT=0.006
NIJA_COMBINED_TRAILING_TP_ACTIVATION_PCT=0.008
NIJA_COMBINED_TRAILING_TP_CALLBACK_PCT=0.003
NIJA_COMBINED_SIZE_RISK_PCT=0.005
```

---

## Dashboard One-Click Fill

The dashboard trade execution panel now supports:

- Calculate Size.
- One-Click Fill.
- Calculated notional.
- Calculated quantity.
- Protection stop price.
- Risk budget.
- Full sizing preview.

Browser console signal:

```text
COMBINED_TRAILING_PANEL_ONE_CLICK_FILL
```

---

## Deployment Verification Logs

After redeploy, confirm:

```text
BROKER_VENUE_CASH_GUARD_IMPORT_HOOK_INSTALLED
POSITION_CLOSE_PNL_IMPORT_HOOK_INSTALLED
AUTO_EXIT_SL_TP_IMPORT_HOOK_INSTALLED
TRAILING_STOP_BRIDGE_INSTALLED
BREAKEVEN_STOP_BRIDGE_INSTALLED
COMBO_BE_TRAILING_BRIDGE_INSTALLED
TRAILING_TP_BRIDGE_INSTALLED
COMBINED_TRAILING_BRIDGE_INSTALLED
COMBINED_TRAILING_SIZE_ENGINE_PATCHED
AUTO_EXIT_SL_TP_MONITOR_STARTED
COMBINED_TRAILING_MONITOR_STARTED
```

---

## Final Product Vision

NIJA AI Trading is being built to become a trusted mobile AI trading system that helps users understand the market, control risk, and make informed trading decisions before using live capital.

NIJA is education-first, user-controlled, broker-direct, and risk-transparent.

---

## Important Disclaimer

NIJA AI Trading is not financial advice.

Trading involves risk and may result in financial loss. Users are responsible for their own trading decisions. NIJA AI Trading does not guarantee profits, returns, income, or trading success.