#!/usr/bin/env python3
"""Keep Kraken recovery from owning canonical broker prebootstrap (v400).

The canonical bot_main startup path is the sole owner of writer-scoped broker
prebootstrap.  The legacy recovery coordinator may observe that prebootstrap has
completed and then start authenticated Kraken recovery, but it must not call the
prebootstrap routine itself from a background thread.  Doing so can race the
main thread between writer verification and Step 1/core registration.

This source patch is intentionally narrow.  It does not grant readiness,
execution authority, nonce authority, LIVE_ACTIVE, or submit/cancel orders.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "canonical_broker_startup_convergence_v24.py"
MARKER = "20260907-kraken-recovery-coordinator-single-owner-v400"

OLD = '''                else:\n                    try:\n                        _prepare_canonical_manager()\n                        if _KRAKEN_RECOVERY_STARTED:\n                            logger.info(\n                                "KRAKEN_RECOVERY_COORDINATOR_HANDOFF marker=%s "\n                                "writer_lineage=true recovery_started=true",\n                                marker,\n                            )\n                            return\n                        reason = "canonical_manager_ready_recovery_not_started"\n                    except Exception as exc:\n                        reason = f"{type(exc).__name__}:{exc}"\n'''

NEW = '''                else:\n                    prebootstrap_ready = (\n                        _truthy("NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_READY")\n                        or _truthy("NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY")\n                    )\n                    if not prebootstrap_ready:\n                        reason = "waiting_for_canonical_bot_main_prebootstrap_owner"\n                    else:\n                        try:\n                            manager_module = importlib.import_module(\n                                "bot.multi_account_broker_manager"\n                            )\n                            manager = getattr(\n                                manager_module, "multi_account_broker_manager", None\n                            )\n                            if manager is None:\n                                getter = getattr(manager_module, "get_broker_manager", None)\n                                manager = getter() if callable(getter) else None\n                            if manager is None or not bool(\n                                getattr(manager, "_fsm_initialized", False)\n                            ):\n                                reason = "canonical_manager_not_ready_after_prebootstrap"\n                            else:\n                                _start_kraken_authenticated_recovery(manager)\n                                if _KRAKEN_RECOVERY_STARTED:\n                                    logger.info(\n                                        "KRAKEN_RECOVERY_COORDINATOR_HANDOFF marker=%s "\n                                        "writer_lineage=true canonical_prebootstrap_owned_by_bot_main=true "\n                                        "recovery_started=true",\n                                        marker,\n                                    )\n                                    return\n                                reason = "canonical_manager_ready_recovery_not_started"\n                        except Exception as exc:\n                            reason = f"{type(exc).__name__}:{exc}"\n'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("KRAKEN_RECOVERY_COORDINATOR_SINGLE_OWNER_V400_ALREADY_APPLIED")
        return
    if OLD not in text:
        raise RuntimeError("v400 coordinator structural anchor not found")
    patched = text.replace(OLD, NEW, 1)
    # Add a stable marker without changing runtime behavior.
    patched = patched.replace(
        '_MARKER = "20260723-canonical-broker-startup-convergence-v24"',
        '_MARKER = "20260723-canonical-broker-startup-convergence-v24"\n'
        f'_KRAKEN_COORDINATOR_SINGLE_OWNER_MARKER = "{MARKER}"',
        1,
    )
    TARGET.write_text(patched, encoding="utf-8")
    print(
        "KRAKEN_RECOVERY_COORDINATOR_SINGLE_OWNER_V400_PATCH_APPLIED "
        "background_prebootstrap=false bot_main_owner=true execution_authority_granted=false "
        "orders_submitted=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
