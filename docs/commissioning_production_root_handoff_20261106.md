# Canonical production startup and commissioning handoff (review only)

## Verified startup owner

`bot/bot_main.py::main` is the canonical process entrypoint in the inspected repository. It acquires writer authority before nonce startup, calls `prepare_canonical_broker_runtime()` in step 0.5, invokes `_run_self_healing_startup()` in step 1, publishes the canonical strategy in step 2.5, and starts `bot.nija_core_loop.start_trading_engine` in step 3.

This identifies the process startup owner, **not** a proven trusted commissioning composition root. The broker returned by self-healing startup is not by itself proof of the exact canonical `KrakenBroker` instance, its authenticated scope, or its terminal dispatch route.

## Existing contracts to reuse

- `bot.kraken_reviewed_collector_bridge.compose_authenticated_kraken_collector_sources`: creates the 13-provider mapping from reviewed authenticated sources. Construction does not install it.
- `bot.kraken_collector_composition_v487.install_reviewed_kraken_collector`: registers evidence after independently reviewed bindings and required certifications.
- `bot.commissioning_runtime.compose_commissioning_runtime`: composes the gate, signed readers and disabled dispatch adapter from trusted evidence and authorization inputs.
- `bot.commissioning_runtime.install_commissioning_dispatch_adapter`: validates the shared collector, fence, ledger, candidate provider, canonical broker and direct terminal, and refuses installation without review and an enabled adapter.
- `bot.execution_pipeline.ExecutionPipeline._dispatch`: consumes an installed commissioning adapter only when the shared admission and terminal bindings match.

## Required production binding proof before installation

1. Trace the actual `bot_main` startup path through canonical broker prebootstrap, self-healing and core loop to the single active `ExecutionPipeline` and its broker terminal. Identify the precise instance owner and startup ordering.
2. Establish exact `KrakenBroker` type, `platform:kraken` authenticated scope and independently approved API-key/IBAN identity pins. Do not substitute configured identity for missing authenticated evidence.
3. Supply thirteen distinct, callable, reviewed provider sources and fresh exchange/ledger/Redis observations; retain source owners and trusted provider IDs.
4. Verify the existing collector/fence/ledger and candidate-provider identities match the active pipeline and commissioning gate; never construct parallel writer, nonce or admission authorities.
5. Reconcile pending Kraken closes, protective-order exchange IDs, positions, risk snapshots, kill-switch state, durable writer lease, nonce sequence and backup/restore certification.
6. Validate signed general operator authorization and separate signed first-order approval using approved trust roots, deployment tuple and exact trade envelope.
7. Require independently reviewed activation, regression/security CI and read-back of the actual production image before any adapter installation or order enablement.

## Fail-closed decision

Do **not** call `install_reviewed_kraken_collector` or `install_commissioning_dispatch_adapter` automatically from `bot_main.main` on the basis of this document. The available repository wiring does not yet demonstrate that the real pipeline, approved sources and independent signatures exist at this boundary. Startup must preserve its current order authority and risk/exit behavior. No environment-variable shortcut, implicit review flag, dummy provider or synthesized approval is permitted.

## Verification

This document is a static code-trace artifact. It does not represent authenticated Render/Kraken/Redis observations, completed regression testing, production installation or trading activation.
