#!/usr/bin/env python3
"""Apply NIJA startup liveness repairs v414/v415/v417.

v414 reuses an already-hydrated CapitalAuthority snapshot during
CapitalAllocationBrain construction so strategy startup cannot be blocked by a
second synchronous broker refresh.

v415 chains a provenance-safe Kraken PLATFORM balance observer into production
runtime convergence. Only a genuinely new, authenticated, credential-proven
PLATFORM Balance read may feed CapitalAuthority; cached reads and user-account
balances cannot refresh platform capital.

v417 repairs the base v281 all-account denominator. Kraken user reconstruction
can leave a retired broker in ``user_brokers`` while the authenticated
replacement is already in ``_all_user_brokers``. The old v281 loop always let
``user_brokers`` overwrite the replacement. v417 chooses the strongest already-
existing broker object across both registries: connected first, then a genuinely
current successful v285 snapshot under the unchanged v285 TTL, then newest
snapshot/fetch/adoption generation. It performs no broker I/O and does not
mutate either registry.

None of these repairs grants readiness synthetically, extends freshness TTLs,
forces activation, starts a trade, or relaxes writer/nonce/risk/kill-switch/
position/protection/order/fill gates.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "capital_allocation_brain.py"
V88 = ROOT / "bot" / "production_runtime_convergence_v88_patch.py"
V281 = ROOT / "bot" / "runtime_all_account_position_exit_coverage_v281_patch.py"
MARKER = "20260914-capital-brain-init-nonblocking-v414"
V415_MARKER = "20260914-kraken-platform-balance-capital-feed-v415"
V417_MARKER = "20260914-v281-canonical-user-object-selection-v417"

OLD = '''            else:\n                self.refresh_authority()\n        \n        logger.info(\n'''

NEW = '''            else:\n                # v414: hydration already proves that CapitalAuthority has an\n                # authoritative snapshot. Do not synchronously start a second\n                # MABM/private balance refresh from inside the strategy\n                # constructor; canonical capital freshness/execution gates still\n                # validate the snapshot independently before entries are allowed.\n                if self.capital_authority.is_hydrated:\n                    self._bootstrap_phase = False\n                    logger.critical(\n                        "CAPITAL_BRAIN_INIT_V414_HYDRATED_REUSE "\n                        "marker=20260914-capital-brain-init-nonblocking-v414 "\n                        "capital=%.2f synchronous_mabm_refresh=false "\n                        "capital_freshness_granted=false execution_authority_unchanged=true "\n                        "safety_gates_bypassed=false",\n                        float(self.capital_authority.total_capital),\n                    )\n                else:\n                    logger.warning(\n                        "CAPITAL_BRAIN_INIT_V414_HYDRATION_RACE "\n                        "marker=20260914-capital-brain-init-nonblocking-v414 "\n                        "async_recovery=true capital_freshness_granted=false "\n                        "execution_authority_unchanged=true safety_gates_bypassed=false"\n                    )\n                    self._start_async_authority_bootstrap()\n        \n        logger.info(\n'''

V88_ANCHOR = '''        if installed:\n            from bot import runtime_heartbeat_position_cap_result_bridge_v303_patch as v303\n            installed = bool(v303.install_import_hook())\n'''

V88_REPLACEMENT = V88_ANCHOR + '''        if installed:\n            from bot import runtime_kraken_platform_balance_capital_feed_v415_patch as v415\n            installed = bool(v415.install_import_hook())\n'''

V281_HELPER_ANCHOR = '''def _platform_key(broker_type: Any) -> str:\n    venue = _label(broker_type)\n    return f"platform:{venue}" if venue else ""\n\n\n'''

V281_HELPER = V281_HELPER_ANCHOR + '''def _user_broker_truth_score_v417(broker: Any) -> tuple[int, int, float, int, int, int]:\n    """Rank duplicate user broker objects using existing local proof only."""\n    if broker is None:\n        return (0, 0, 0.0, 0, 0, 0)\n    connected = 1 if _connected(broker) else 0\n    fetch = 1 if getattr(broker, "_startup_position_sync_fetch_ok", None) is True else 0\n    adopted = 1 if getattr(broker, "_startup_position_sync_adopted", None) is True else 0\n    snapshot_at = _float(\n        getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0),\n        0.0,\n    )\n    try:\n        generation = int(\n            getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0\n        )\n    except Exception:\n        generation = 0\n    try:\n        ttl = float(os.environ.get("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "90") or 90.0)\n    except (TypeError, ValueError):\n        ttl = 90.0\n    ttl = max(15.0, min(600.0, ttl))\n    age_s = max(0.0, time.monotonic() - snapshot_at) if snapshot_at > 0.0 else float("inf")\n    current_snapshot = int(\n        connected\n        and getattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", None) is True\n        and hasattr(broker, "_nija_authoritative_position_snapshot_rows_v285")\n        and snapshot_at > 0.0\n        and age_s <= ttl\n    )\n    return (connected, current_snapshot, snapshot_at, fetch, adopted, generation)\n\n\ndef _select_user_broker_v417(expected: dict[str, Any], key: str, broker: Any) -> None:\n    """Choose stronger duplicate identity without mutating manager registries."""\n    current = expected.get(key)\n    if current is None or _user_broker_truth_score_v417(broker) > _user_broker_truth_score_v417(current):\n        expected[key] = broker\n\n\n'''

V281_OLD_ALL_USERS = '''            key = _user_key(raw_key[0], raw_key[1])\n            if key and key not in disabled:\n                expected[key] = broker\n\n    for user_id, broker_map in _iter_items(getattr(manager, "user_brokers", {})):\n        for broker_type, broker in _iter_items(broker_map):\n            key = _user_key(user_id, broker_type)\n            if key and key not in disabled:\n                expected[key] = broker\n'''

V281_NEW_ALL_USERS = '''            key = _user_key(raw_key[0], raw_key[1])\n            if key and key not in disabled:\n                _select_user_broker_v417(expected, key, broker)\n\n    for user_id, broker_map in _iter_items(getattr(manager, "user_brokers", {})):\n        for broker_type, broker in _iter_items(broker_map):\n            key = _user_key(user_id, broker_type)\n            if key and key not in disabled:\n                _select_user_broker_v417(expected, key, broker)\n'''


def _patch_v414() -> bool:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print(
            f"CAPITAL_BRAIN_INIT_NONBLOCKING_V414_ALREADY_APPLIED marker={MARKER} "
            "synchronous_mabm_refresh=false capital_ttl_unchanged=true "
            "execution_authority_unchanged=true safety_gates_bypassed=false"
        )
        return False
    if text.count(OLD) != 1:
        raise SystemExit("v414 expected exactly one CapitalAllocationBrain init refresh anchor")
    TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)
    print(
        f"CAPITAL_BRAIN_INIT_NONBLOCKING_V414_PATCH_APPLIED marker={MARKER} "
        "hydrated_authority_reused=true synchronous_mabm_refresh=false "
        "capital_ttl_unchanged=true capital_freshness_granted=false "
        "execution_authority_unchanged=true safety_gates_bypassed=false"
    )
    return True


def _patch_v415_chain() -> bool:
    text = V88.read_text(encoding="utf-8")
    if "runtime_kraken_platform_balance_capital_feed_v415_patch" in text:
        print(
            f"KRAKEN_PLATFORM_BALANCE_CAPITAL_FEED_V415_CHAIN_ALREADY_APPLIED marker={V415_MARKER} "
            "new_broker_io=false forced_activation=false safety_gates_bypassed=false"
        )
        return False
    if text.count(V88_ANCHOR) != 1:
        raise SystemExit("v415 expected exactly one v303 runtime convergence anchor")
    V88.write_text(text.replace(V88_ANCHOR, V88_REPLACEMENT, 1), encoding="utf-8")
    py_compile.compile(str(V88), doraise=True)
    print(
        f"KRAKEN_PLATFORM_BALANCE_CAPITAL_FEED_V415_CHAIN_APPLIED marker={V415_MARKER} "
        "platform_only=true authenticated_balance_required=true cached_call_cannot_refresh=true "
        "new_broker_io=false capital_ttl_unchanged=true forced_activation=false "
        "safety_gates_bypassed=false"
    )
    return True


def _patch_v417() -> bool:
    text = V281.read_text(encoding="utf-8")
    if V417_MARKER in text or "_user_broker_truth_score_v417" in text:
        print(
            f"V281_CANONICAL_USER_OBJECT_SELECTION_V417_ALREADY_APPLIED marker={V417_MARKER} "
            "broker_io=false registry_mutation=false snapshot_ttl_unchanged=true "
            "safety_gates_bypassed=false"
        )
        return False
    if "import time\n" not in text:
        import_anchor = "import threading\n"
        if text.count(import_anchor) != 1:
            raise SystemExit("v417 expected one threading import anchor")
        text = text.replace(import_anchor, import_anchor + "import time\n", 1)
    if text.count(V281_HELPER_ANCHOR) != 1:
        raise SystemExit("v417 expected one v281 platform-key helper anchor")
    text = text.replace(V281_HELPER_ANCHOR, V281_HELPER, 1)
    if text.count(V281_OLD_ALL_USERS) != 1:
        raise SystemExit("v417 expected one v281 user registry overwrite block")
    text = text.replace(V281_OLD_ALL_USERS, V281_NEW_ALL_USERS, 1)
    # Embed a stable release marker in executable source for idempotence and audit.
    text = text.replace(
        'MARKER = "20260829-all-account-position-exit-coverage-v281"\n',
        'MARKER = "20260829-all-account-position-exit-coverage-v281"\n'
        'V417_MARKER = "20260914-v281-canonical-user-object-selection-v417"\n',
        1,
    )
    V281.write_text(text, encoding="utf-8")
    py_compile.compile(str(V281), doraise=True)
    print(
        f"V281_CANONICAL_USER_OBJECT_SELECTION_V417_PATCH_APPLIED marker={V417_MARKER} "
        "connected_replacement_preferred=true current_v285_snapshot_preferred=true "
        "newest_snapshot_tiebreak=true completed_fetch_failure_not_current=true "
        "broker_io=false registry_mutation=false snapshot_ttl_unchanged=true "
        "readiness_fabricated=false safety_gates_bypassed=false"
    )
    return True


def main() -> int:
    _patch_v414()
    _patch_v415_chain()
    _patch_v417()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
