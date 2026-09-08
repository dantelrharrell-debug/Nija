#!/usr/bin/env python3
"""Keep background Kraken recovery from owning canonical broker prebootstrap.

The canonical bot_main startup path is the sole owner of writer-scoped broker
prebootstrap. Background Kraken recovery paths may observe that prebootstrap has
completed and then reconcile/recover connectivity, but they must never invoke
the canonical prebootstrap routine themselves before bot_main reaches its core
registration path.

This source patch is intentionally narrow. It does not grant readiness,
execution authority, nonce authority, LIVE_ACTIVE, or submit/cancel orders.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V24_TARGET = ROOT / "bot" / "canonical_broker_startup_convergence_v24.py"
V44_TARGET = ROOT / "bot" / "kraken_connection_convergence_v44_patch.py"
MARKER = "20260907-kraken-recovery-coordinator-single-owner-v400"
V44_MARKER = "20260907-kraken-v44-prebootstrap-single-owner-v400"

V24_OLD = '''                else:\n                    try:\n                        _prepare_canonical_manager()\n                        if _KRAKEN_RECOVERY_STARTED:\n                            logger.info(\n                                "KRAKEN_RECOVERY_COORDINATOR_HANDOFF marker=%s "\n                                "writer_lineage=true recovery_started=true",\n                                marker,\n                            )\n                            return\n                        reason = "canonical_manager_ready_recovery_not_started"\n                    except Exception as exc:\n                        reason = f"{type(exc).__name__}:{exc}"\n'''

V24_NEW = '''                else:\n                    prebootstrap_ready = (\n                        _truthy("NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_READY")\n                        or _truthy("NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY")\n                    )\n                    if not prebootstrap_ready:\n                        reason = "waiting_for_canonical_bot_main_prebootstrap_owner"\n                    else:\n                        try:\n                            manager_module = importlib.import_module(\n                                "bot.multi_account_broker_manager"\n                            )\n                            manager = getattr(\n                                manager_module, "multi_account_broker_manager", None\n                            )\n                            if manager is None:\n                                getter = getattr(manager_module, "get_broker_manager", None)\n                                manager = getter() if callable(getter) else None\n                            if manager is None or not bool(\n                                getattr(manager, "_fsm_initialized", False)\n                            ):\n                                reason = "canonical_manager_not_ready_after_prebootstrap"\n                            else:\n                                _start_kraken_authenticated_recovery(manager)\n                                if _KRAKEN_RECOVERY_STARTED:\n                                    logger.info(\n                                        "KRAKEN_RECOVERY_COORDINATOR_HANDOFF marker=%s "\n                                        "writer_lineage=true canonical_prebootstrap_owned_by_bot_main=true "\n                                        "recovery_started=true",\n                                        marker,\n                                    )\n                                    return\n                                reason = "canonical_manager_ready_recovery_not_started"\n                        except Exception as exc:\n                            reason = f"{type(exc).__name__}:{exc}"\n'''

V44_OLD = '''    broker = _canonical_kraken(manager)\n    if broker is None:\n        prepare = getattr(v24, "_prepare_canonical_manager", None)\n        if callable(prepare):\n            try:\n                manager = prepare()\n                broker = _canonical_kraken(manager)\n            except Exception as exc:\n                result["reason"] = f"canonical_prepare_failed:{type(exc).__name__}:{exc}"\n                return result\n    if broker is None:\n        result["reason"] = "canonical_kraken_unavailable"\n        return result\n'''

V44_NEW = '''    broker = _canonical_kraken(manager)\n    if broker is None:\n        prebootstrap_ready = (\n            _truthy("NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_READY")\n            or _truthy("NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY")\n        )\n        if not prebootstrap_ready:\n            result["reason"] = "waiting_for_canonical_bot_main_prebootstrap_owner"\n            result["action"] = "observe"\n            return result\n    if broker is None:\n        result["reason"] = "canonical_kraken_unavailable"\n        return result\n'''


def _patch_v24() -> str:
    text = V24_TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        return "already_applied"
    if V24_OLD not in text:
        raise RuntimeError("v400 coordinator structural anchor not found")
    patched = text.replace(V24_OLD, V24_NEW, 1)
    patched = patched.replace(
        '_MARKER = "20260723-canonical-broker-startup-convergence-v24"',
        '_MARKER = "20260723-canonical-broker-startup-convergence-v24"\n'
        f'_KRAKEN_COORDINATOR_SINGLE_OWNER_MARKER = "{MARKER}"',
        1,
    )
    V24_TARGET.write_text(patched, encoding="utf-8")
    return "patched"


def _patch_v44() -> str:
    text = V44_TARGET.read_text(encoding="utf-8")
    if V44_MARKER in text:
        return "already_applied"
    if V44_OLD not in text:
        raise RuntimeError("v400 v44 structural anchor not found")
    patched = text.replace(V44_OLD, V44_NEW, 1)
    patched = patched.replace(
        'MARKER = "20260807-kraken-connection-convergence-v44"',
        'MARKER = "20260807-kraken-connection-convergence-v44"\n'
        f'PREBOOTSTRAP_SINGLE_OWNER_MARKER = "{V44_MARKER}"',
        1,
    )
    V44_TARGET.write_text(patched, encoding="utf-8")
    return "patched"


def main() -> None:
    v24_status = _patch_v24()
    v44_status = _patch_v44()
    print(
        "KRAKEN_RECOVERY_COORDINATOR_SINGLE_OWNER_V400_PATCH_APPLIED "
        f"v24={v24_status} v44={v44_status} background_prebootstrap=false "
        "bot_main_owner=true execution_authority_granted=false orders_submitted=false "
        "safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
