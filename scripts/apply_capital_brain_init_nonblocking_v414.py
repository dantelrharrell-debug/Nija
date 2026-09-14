#!/usr/bin/env python3
"""Avoid redundant strategy-init capital refresh and install v415 capital feed.

v414 reuses an already-hydrated CapitalAuthority snapshot during
CapitalAllocationBrain construction so strategy startup cannot be blocked by a
second synchronous broker refresh.

v415 is a separate liveness repair applied to production_runtime_convergence_v88:
it chains the provenance-safe Kraken PLATFORM balance observer into the normal
runtime supervision installer. The v415 runtime patch only feeds CapitalAuthority
when the same get_account_balance invocation performed a new authenticated,
credential-proven PLATFORM Balance read. Cached calls cannot refresh capital and
user-account balances never enter platform capital.

Neither repair grants capital freshness synthetically, forces activation, starts
a trade, or relaxes writer/nonce/risk/kill-switch/position/protection/order/fill
gates.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "capital_allocation_brain.py"
V88 = ROOT / "bot" / "production_runtime_convergence_v88_patch.py"
MARKER = "20260914-capital-brain-init-nonblocking-v414"
V415_MARKER = "20260914-kraken-platform-balance-capital-feed-v415"

OLD = '''            else:\n                self.refresh_authority()\n        \n        logger.info(\n'''

NEW = '''            else:\n                # v414: hydration already proves that CapitalAuthority has an\n                # authoritative snapshot. Do not synchronously start a second\n                # MABM/private balance refresh from inside the strategy\n                # constructor; canonical capital freshness/execution gates still\n                # validate the snapshot independently before entries are allowed.\n                if self.capital_authority.is_hydrated:\n                    self._bootstrap_phase = False\n                    logger.critical(\n                        "CAPITAL_BRAIN_INIT_V414_HYDRATED_REUSE "\n                        "marker=20260914-capital-brain-init-nonblocking-v414 "\n                        "capital=%.2f synchronous_mabm_refresh=false "\n                        "capital_freshness_granted=false execution_authority_unchanged=true "\n                        "safety_gates_bypassed=false",\n                        float(self.capital_authority.total_capital),\n                    )\n                else:\n                    logger.warning(\n                        "CAPITAL_BRAIN_INIT_V414_HYDRATION_RACE "\n                        "marker=20260914-capital-brain-init-nonblocking-v414 "\n                        "async_recovery=true capital_freshness_granted=false "\n                        "execution_authority_unchanged=true safety_gates_bypassed=false"\n                    )\n                    self._start_async_authority_bootstrap()\n        \n        logger.info(\n'''

V88_ANCHOR = '''        if installed:\n            from bot import runtime_heartbeat_position_cap_result_bridge_v303_patch as v303\n            installed = bool(v303.install_import_hook())\n'''

V88_REPLACEMENT = V88_ANCHOR + '''        if installed:\n            from bot import runtime_kraken_platform_balance_capital_feed_v415_patch as v415\n            installed = bool(v415.install_import_hook())\n'''


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


def main() -> int:
    _patch_v414()
    _patch_v415_chain()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
