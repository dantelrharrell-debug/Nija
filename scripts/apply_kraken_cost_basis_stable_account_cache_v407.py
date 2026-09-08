#!/usr/bin/env python3
"""Apply fail-closed Kraken authenticated cost-basis cache identity repair v407.

v288 caches genuine authenticated Kraken bulk entry-price results so a later
startup-position adoption pass can consume them. Production on 2026-09-08 showed
user reconciliation can recreate the broker wrapper between the history worker
and the adoption retry. v288 keyed its flight/cache by ``id(real_broker)``, so a
new wrapper/real-broker object could miss the completed genuine result and start
another authenticated history flight indefinitely.

v407 changes only the in-process flight/cache identity for Kraken to a stable,
non-secret account identity (``account_identifier`` when present, otherwise the
existing object id). It does not create, alter, or infer any price. Cached values
must still originate from v288/v304 authenticated broker history and remain
subject to the unchanged v288 cache TTL and all downstream quantity, position,
protection, readiness, nonce, writer, capital, risk, kill-switch, order and fill
gates. No orders are submitted and no position/readiness is fabricated.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "runtime_kraken_cost_basis_bulk_v288_patch.py"
MARKER = "20260908-kraken-cost-basis-stable-account-cache-v407"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print(
            "KRAKEN_COST_BASIS_STABLE_ACCOUNT_CACHE_V407_PATCH_APPLIED "
            f"marker={MARKER} changed=false authenticated_history_only=true "
            "cache_ttl_unchanged=true orders_submitted=false cost_basis_fabricated=false "
            "readiness_fabricated=false safety_gates_bypassed=false"
        )
        return

    anchor = '''def _is_kraken(broker: Any) -> bool:\n    real = _real_broker(broker)\n    if real is None:\n        return False\n    if _label(getattr(real, "broker_type", "")) == "kraken":\n        return True\n    return type(real).__name__.lower() == "krakenbroker"\n\n\n'''
    if anchor not in text:
        raise RuntimeError("v407 expected v288 kraken identity anchor missing")

    helper = anchor + '''# v407: preserve a completed genuine authenticated history result across\n# reconciliation wrapper recreation for the same Kraken account.  The key is\n# identity only; it never supplies or validates an entry price.\ndef _stable_bulk_key_v407(real: Any) -> Any:\n    account = str(getattr(real, "account_identifier", "") or "").strip().lower()\n    if account:\n        return ("kraken-account", account)\n    return ("broker-object", id(real))\n\n\n'''
    text = text.replace(anchor, helper, 1)

    old = "    key = id(real)\n"
    new = "    key = _stable_bulk_key_v407(real)\n"
    if old not in text:
        raise RuntimeError("v407 expected v288 object-id cache key missing")
    text = text.replace(old, new, 1)

    # Add a source marker without changing runtime behavior.
    marker_anchor = 'MARKER = "20260830-kraken-cost-basis-bulk-v288"\n'
    if marker_anchor not in text:
        raise RuntimeError("v407 expected v288 marker anchor missing")
    text = text.replace(
        marker_anchor,
        marker_anchor + f'V407_STABLE_ACCOUNT_CACHE_MARKER = "{MARKER}"\n',
        1,
    )

    TARGET.write_text(text, encoding="utf-8")
    print(
        "KRAKEN_COST_BASIS_STABLE_ACCOUNT_CACHE_V407_PATCH_APPLIED "
        f"marker={MARKER} changed=true stable_account_identity=true authenticated_history_only=true "
        "cache_ttl_unchanged=true snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true "
        "orders_submitted=false cost_basis_fabricated=false readiness_fabricated=false "
        "eligibility_fabricated=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
