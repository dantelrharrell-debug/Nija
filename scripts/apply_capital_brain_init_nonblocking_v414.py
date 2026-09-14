#!/usr/bin/env python3
"""Avoid a redundant synchronous CapitalAuthority refresh during strategy init.

Production showed CapitalAllocationBrain construction entering a fresh MABM
capital refresh immediately after CapitalAuthority was already hydrated. That
private read can legitimately take up to 75 seconds, while canonical strategy
publication is fail-closed at 45 seconds, so startup can never reach core
registration even though authoritative capital is already available.

v414 reuses the already-hydrated CapitalAuthority snapshot only for constructor
initialization and marks the brain's bootstrap phase complete. It does not mark
capital fresh, grant execution authority, change any capital TTL, skip normal
runtime refreshes, or relax writer/nonce/risk/kill-switch/position/protection/
order/fill gates. Downstream canonical capital-readiness gates remain
responsible for freshness and execution eligibility.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "capital_allocation_brain.py"
MARKER = "20260914-capital-brain-init-nonblocking-v414"

OLD = '''            else:\n                self.refresh_authority()\n        \n        logger.info(\n'''

NEW = '''            else:\n                # v414: hydration already proves that CapitalAuthority has an\n                # authoritative snapshot. Do not synchronously start a second\n                # MABM/private balance refresh from inside the strategy\n                # constructor; canonical capital freshness/execution gates still\n                # validate the snapshot independently before entries are allowed.\n                if self.capital_authority.is_hydrated:\n                    self._bootstrap_phase = False\n                    logger.critical(\n                        "CAPITAL_BRAIN_INIT_V414_HYDRATED_REUSE "\n                        "marker=20260914-capital-brain-init-nonblocking-v414 "\n                        "capital=%.2f synchronous_mabm_refresh=false "\n                        "capital_freshness_granted=false execution_authority_unchanged=true "\n                        "safety_gates_bypassed=false",\n                        float(self.capital_authority.total_capital),\n                    )\n                else:\n                    logger.warning(\n                        "CAPITAL_BRAIN_INIT_V414_HYDRATION_RACE "\n                        "marker=20260914-capital-brain-init-nonblocking-v414 "\n                        "async_recovery=true capital_freshness_granted=false "\n                        "execution_authority_unchanged=true safety_gates_bypassed=false"\n                    )\n                    self._start_async_authority_bootstrap()\n        \n        logger.info(\n'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print(
            f"CAPITAL_BRAIN_INIT_NONBLOCKING_V414_ALREADY_APPLIED marker={MARKER} "
            "synchronous_mabm_refresh=false capital_ttl_unchanged=true "
            "execution_authority_unchanged=true safety_gates_bypassed=false"
        )
        return 0
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
