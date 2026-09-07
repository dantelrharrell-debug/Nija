#!/usr/bin/env python3
"""Guarantee Kraken margin v367 -> v368 -> v371 post-ready handoff.

The existing v368 module owns exact-broker hard-exit scoping and installs the
existing v371 four-way protection verifier. Some canonical fast-path startups
install v367 without subsequently invoking v368, leaving authenticated margin
positions visible but final four-way certification absent.

This source patch makes v367 start the existing v368/v371 chain asynchronously
only after v367 has genuinely published ready. It does not create protection,
extend freshness, grant execution authority, clear a kill switch, alter risk
limits, or submit an order. Any install failure remains fail closed and retries
with bounded cadence.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "runtime_kraken_margin_protection_truth_v367_patch.py"
MARKER = "20260907-kraken-margin-protection-chain-v386"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "KRAKEN_MARGIN_V368_V371_CHAIN_V386_READY" in text:
        print(
            "KRAKEN_MARGIN_PROTECTION_CHAIN_V386_PATCH_APPLIED "
            f"marker={MARKER} changed=false idempotent=true"
        )
        return

    install_anchor = "\ndef install_import_hook() -> bool:\n"
    if install_anchor not in text:
        raise RuntimeError("v367 install anchor not found")

    helper = '''\n\n# v386: guarantee the existing exact-broker v368 -> v371 chain is installed\n# after v367 is genuinely ready, without blocking canonical startup.\n_V368_CHAIN_THREAD_V386 = None\n\n\ndef _start_v368_chain_v386() -> bool:\n    global _V368_CHAIN_THREAD_V386\n    with _LOCK:\n        if _V368_CHAIN_THREAD_V386 is not None and _V368_CHAIN_THREAD_V386.is_alive():\n            return True\n\n        def _worker() -> None:\n            # Let the current v367 installer release its lock before v368 reads\n            # and wraps v367 surfaces. Shutdown remains authoritative via _STOP.\n            if _STOP.wait(0.50):\n                return\n            last_error = "not_attempted"\n            for attempt in range(1, 61):\n                if _STOP.is_set():\n                    return\n                if os.environ.get(_READY_FLAG) != "1":\n                    last_error = "v367_not_ready"\n                    if _STOP.wait(1.0):\n                        return\n                    continue\n                try:\n                    module = importlib.import_module(\n                        "bot.runtime_kraken_margin_protection_authority_v368_patch"\n                    )\n                    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)\n                    if callable(installer) and bool(installer()):\n                        LOGGER.critical(\n                            "KRAKEN_MARGIN_V368_V371_CHAIN_V386_READY "\n                            "marker=20260907-kraken-margin-protection-chain-v386 attempt=%d "\n                            "v367_ready=true v368_v371_existing_chain=true async_handoff=true "\n                            "protection_fabricated=false execution_authority_unchanged=true "\n                            "risk_gates_unchanged=true orders_submitted=false safety_gates_bypassed=false",\n                            attempt,\n                        )\n                        return\n                    last_error = "v368_installer_not_ready"\n                except Exception as exc:\n                    last_error = f"{type(exc).__name__}:{exc}"\n                    LOGGER.warning(\n                        "KRAKEN_MARGIN_V368_V371_CHAIN_V386_RETRY "\n                        "marker=20260907-kraken-margin-protection-chain-v386 attempt=%d error=%s "\n                        "trading_fail_closed=true protection_fabricated=false orders_submitted=false",\n                        attempt, last_error,\n                    )\n                if _STOP.wait(2.0):\n                    return\n            LOGGER.error(\n                "KRAKEN_MARGIN_V368_V371_CHAIN_V386_DEFERRED "\n                "marker=20260907-kraken-margin-protection-chain-v386 attempts=60 last_error=%s "\n                "trading_fail_closed=true protection_fabricated=false orders_submitted=false",\n                last_error,\n            )\n\n        _V368_CHAIN_THREAD_V386 = threading.Thread(\n            target=_worker,\n            name="KrakenMarginV368V371ChainV386",\n            daemon=True,\n        )\n        _V368_CHAIN_THREAD_V386.start()\n        return bool(_V368_CHAIN_THREAD_V386.is_alive())\n'''
    text = text.replace(install_anchor, helper + install_anchor, 1)

    call_anchor = '''            _wake_coverage()\n        return ready\n'''
    call_replacement = '''            _wake_coverage()\n            chain_started = _start_v368_chain_v386()\n            LOGGER.info(\n                "KRAKEN_MARGIN_V368_V371_CHAIN_V386_STARTED "\n                "marker=20260907-kraken-margin-protection-chain-v386 started=%s "\n                "async_handoff=true v367_ready=true trading_fail_closed_until_v371=true "\n                "orders_submitted=false safety_gates_bypassed=false",\n                str(bool(chain_started)).lower(),\n            )\n        return ready\n'''
    if call_anchor not in text:
        raise RuntimeError("v367 ready handoff anchor not found")
    text = text.replace(call_anchor, call_replacement, 1)
    TARGET.write_text(text, encoding="utf-8")

    print(
        "KRAKEN_MARGIN_PROTECTION_CHAIN_V386_PATCH_APPLIED "
        f"marker={MARKER} changed=true v367_to_v368_v371_async=true "
        "risk_gates_unchanged=true freshness_unchanged=true "
        "protection_fabricated=false execution_authority_unchanged=true "
        "orders_submitted=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
