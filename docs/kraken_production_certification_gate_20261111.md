# Kraken production certification evidence gate — 2026-11-11 (review only)

## Scope and authority
Existing Render service `srv-d98dsr5aeets73fpbaqg`, workspace `tea-d37fhe8gjchc73c8eo0g`. This is an evidence-based release hold, **not** a collector installation, order authorization, production configuration change, or permission to bypass admission. Preserve `allow_new_orders=false` until independently certified.

## Latest observed production evidence
- Render latest observed live deployment: `dep-dbqbg0jl550s73eme9c0`, SHA `27e5538f58260ded17aae6c4008052b5fb8a2743`, completed 2026-11-11 18:51:46 UTC.
- Render app logs 2026-11-11 19:22:13–19:22:24 UTC: `PRETRADE_INDEPENDENT_CERTIFICATION_V6 ready=false account_scope_configured=true producer_status=collector_missing collector_installed=false diagnostic_only=true`.
- All thirteen named pretrade checks were missing **because the collector was absent**, not independently proven failed: `account_permissions`, `account_identity`, `broker_balances`, `position_ledger_reconciliation`, `protective_exit_readback`, `open_order_reconciliation`, `duplicate_order_fence`, `writer_lease`, `nonce_sequence`, `operator_authorization`, `kill_switch_clear`, `risk_limits`, `position_sync`.
- Earlier 2026-11-11 18:22 UTC logs: `execution_ready=false`, `execution_authority=false`, `trading_engine_ready=false`; `PREACTIVATION_EXECUTION_PROOF_V16 ready=false producer=missing failing_condition=verification_stale`.
- A healthy heartbeat or `kill_switch=false` in one log entry is **not** independent certification of all admission gates.

## Existing reviewed interfaces — do not invent replacements
- Canonical process entrypoint: `bot/bot_main.py::main`.
- `bot.kraken_reviewed_collector_bridge.compose_authenticated_kraken_collector_sources`: build 13-source mapping, not install.
- `bot.kraken_collector_composition_v487.install_reviewed_kraken_collector`: registration only after independent evidence and approved source bindings.
- `bot.commissioning_runtime.compose_commissioning_runtime` and `install_commissioning_dispatch_adapter`: separate commissioning and terminal identity verification.
- `docs/commissioning_production_root_handoff_20261106.md`: explicit no-auto-install policy until canonical broker, shared pipeline, signing custody and all evidence are proven.

## Required independent acceptance evidence (attach redacted references, never secrets)
1. Trace production command and process entry to one canonical `KrakenBroker`, authenticated `platform:kraken` scope, active `ExecutionPipeline` and terminal; prove identical object ownership.
2. Independently approved key fingerprint and account identity pins, authenticated permission readback, no credential leakage; do not derive approved pins from the first live response.
3. Thirteen separately owned provider callbacks, source IDs, collection timestamps and strict freshness; prove registration in the **same interpreter** as canonical main, and verify readback `collector_installed=true`.
4. Complete paginated authenticated Kraken open/closed order and trade history reconciliation against ledger, pending closes, fill/fee lots, positions and exchange protective-order IDs; account for legacy pending closes without deleting or assuming them resolved.
5. Independent durable duplicate-order inventory, Redis kill-switch state, writer lease, nonce sequence, risk limit snapshot, position synchronization and backup/restore proof.
6. Explicit signed operator authorization, independently reviewed trust roots and deployment tuple; no synthesized approvals or environmental shortcut.
7. CI regression/security checks, production image/commit attestation, independent reviewer approval, staged read-only verification, and rollback readiness.
8. After genuine pretrade certification, resolve the **separate** stale legacy execution proof using the approved commissioning migration. Do not manufacture a fill, backdate evidence or authorize broad live dispatch.
9. Before any first live order, obtain separate explicit owner approval of pair, maximum notional, order type and account, then independently verify the actual outcome before any autonomous authorization.

## Fail-closed release decision
**NOT CERTIFIED. DO NOT ACTIVATE OR SUBMIT ORDERS.** This document records an observed blocker and acceptance requirements; it does not certify any provider or install anything. Recheck live logs after an independently reviewed production change and record new evidence before changing the decision.
