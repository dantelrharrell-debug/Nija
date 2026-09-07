#!/usr/bin/env python3
"""Apply fail-closed Kraken coverage truth/fairness convergence v385.

This source patch is intentionally narrow:
1. v366 exposure discovery no longer emits a final-looking
   protective_exit_verified=false telemetry event before v371 has had the
   opportunity to certify the same row. The row/reason semantics remain
   fail-closed and unchanged.
2. v285's single-user authoritative refresh becomes round-robin across all
   connected registered user accounts. Existing retry intervals, snapshot TTL,
   authenticated adopter, broker rate limits, and fail-closed semantics are
   unchanged.

No order submission, execution authority, activation, balance, position,
protection, fill, or freshness proof is fabricated.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V366 = ROOT / "bot" / "runtime_kraken_margin_canonical_coverage_v366_patch.py"
V285 = ROOT / "bot" / "runtime_authoritative_position_coverage_v285_patch.py"
MARKER = "20260907-kraken-coverage-truth-fairness-v385"


def patch_v366() -> bool:
    text = V366.read_text(encoding="utf-8")
    if "KRAKEN_MARGIN_POSITION_PROTECTION_PENDING_V385" in text:
        return False

    old_visible = '''        LOGGER.critical(\n            "KRAKEN_MARGIN_POSITION_VISIBLE marker=%s account=%s broker=%s symbol=%s position_id=%s "\n            "quantity=%.12f entry_price=%.8f cost_basis_usd=%.8f leverage=%s side=long source=%s "\n            "margin_position=true protective_exit_required=true protective_exit_verified=%s "\n            "safety_gates_bypassed=false fill_fabricated=false spot_tracker_mutated=false",\n            MARKER, key, venue, symbol, ",".join(row["position_ids"]) or "unknown",\n            quantity, entry_price, cost_basis, row["leverage"], _SOURCE, "false",\n        )\n'''
    new_visible = '''        LOGGER.critical(\n            "KRAKEN_MARGIN_POSITION_VISIBLE marker=%s account=%s broker=%s symbol=%s position_id=%s "\n            "quantity=%.12f entry_price=%.8f cost_basis_usd=%.8f leverage=%s side=long source=%s "\n            "margin_position=true protective_exit_required=true protection_verification_stage=pre_v371 "\n            "safety_gates_bypassed=false fill_fabricated=false spot_tracker_mutated=false",\n            MARKER, key, venue, symbol, ",".join(row["position_ids"]) or "unknown",\n            quantity, entry_price, cost_basis, row["leverage"], _SOURCE,\n        )\n'''
    old_coverage = '''        LOGGER.critical(\n            "KRAKEN_MARGIN_POSITION_PROTECTIVE_COVERAGE marker=%s account=%s symbol=%s quantity=%.12f "\n            "entry_price=%.8f side=long source=%s margin_position=true protective_exit_required=true "\n            "protective_exit_verified=%s canonical_coverage=false safety_gates_bypassed=false "\n            "fill_fabricated=false spot_tracker_mutated=false",\n            MARKER, key, symbol, quantity, entry_price, _SOURCE, "false",\n        )\n'''
    new_coverage = '''        LOGGER.info(\n            "KRAKEN_MARGIN_POSITION_PROTECTION_PENDING_V385 marker=%s source_marker=%s account=%s symbol=%s "\n            "quantity=%.12f entry_price=%.8f side=long source=%s margin_position=true "\n            "protective_exit_required=true protection_verification_deferred_to_v371=true "\n            "canonical_coverage_stage=pre_v371 row_semantics_unchanged=true safety_gates_bypassed=false "\n            "fill_fabricated=false spot_tracker_mutated=false",\n            "20260907-kraken-coverage-truth-fairness-v385", MARKER, key, symbol, quantity, entry_price, _SOURCE,\n        )\n'''
    if old_visible not in text or old_coverage not in text:
        raise RuntimeError("v366 expected telemetry anchors not found")
    text = text.replace(old_visible, new_visible, 1).replace(old_coverage, new_coverage, 1)
    V366.write_text(text, encoding="utf-8")
    return True


def patch_v285() -> bool:
    text = V285.read_text(encoding="utf-8")
    if "AUTHORITATIVE_USER_POSITION_V385_FAIR_REFRESH" in text:
        return False

    anchor = '''\ndef _kick_user_reconnect(manager: Any) -> dict[str, Any]:\n'''
    if anchor not in text:
        raise RuntimeError("v285 user-refresh insertion anchor not found")

    fair_patch = r'''\n\n# v385: fairness-only replacement for the single-user refresh selector.\n# Snapshot TTL, retry timing, authenticated adopter, rate limits and all\n# fail-closed proof requirements are unchanged.\n_USER_REFRESH_LAST_ACCOUNT_V385 = ""\n\n\ndef _refresh_one_user_v385(manager: Any) -> str:\n    global _USER_REFRESH_LAST_ACCOUNT_V385\n    expected = _expected_accounts(manager)\n    now = time.monotonic()\n    users = [\n        (str(account), broker)\n        for account, broker in expected.items()\n        if str(account).startswith("user:") and broker is not None and _connected(broker)\n    ]\n    users.sort(key=lambda item: item[0])\n    if not users:\n        return "no_user_refresh_needed"\n\n    start = 0\n    if _USER_REFRESH_LAST_ACCOUNT_V385:\n        for idx, (account, _broker) in enumerate(users):\n            if account == _USER_REFRESH_LAST_ACCOUNT_V385:\n                start = (idx + 1) % len(users)\n                break\n    ordered = users[start:] + users[:start]\n\n    selected = None\n    for account, broker in ordered:\n        if now >= _USER_NEXT_REFRESH.get(account, 0.0):\n            selected = (account, broker)\n            break\n    if selected is None:\n        return "no_user_refresh_needed"\n\n    account, broker = selected\n    ready, reason = _strong_broker_proof(broker)\n    if not _USER_REFRESH_LOCK.acquire(blocking=False):\n        return "user_refresh_busy"\n    try:\n        try:\n            sync = importlib.import_module("bot.startup_position_sync")\n            adopter = getattr(sync, "_adopt_broker_positions", None)\n            eps_getter = getattr(sync, "_get_entry_price_store", None)\n            if not callable(adopter):\n                _USER_NEXT_REFRESH[account] = now + _retry_s()\n                _USER_REFRESH_LAST_ACCOUNT_V385 = account\n                return f"{account}:adopter_missing"\n            eps = eps_getter() if callable(eps_getter) else None\n            adopter(broker, account, eps)\n        except Exception as exc:\n            _USER_NEXT_REFRESH[account] = time.monotonic() + _retry_s()\n            _USER_REFRESH_LAST_ACCOUNT_V385 = account\n            LOGGER.warning(\n                "AUTHORITATIVE_USER_POSITION_V385_FAIR_REFRESH_FAILED marker=20260907-kraken-coverage-truth-fairness-v385 "\n                "account=%s prior_reason=%s error=%s:%s fail_closed=true round_robin=true "\n                "snapshot_ttl_unchanged=true retry_interval_unchanged=true synthetic_success=false",\n                account, reason, type(exc).__name__, exc,\n            )\n            return f"{account}:refresh_exception"\n\n        refreshed, refreshed_reason = _strong_broker_proof(broker)\n        _USER_NEXT_REFRESH[account] = time.monotonic() + (\n            _refresh_interval_s() if refreshed else _retry_s()\n        )\n        _USER_REFRESH_LAST_ACCOUNT_V385 = account\n        log = LOGGER.critical if refreshed else LOGGER.warning\n        log(\n            "AUTHORITATIVE_USER_POSITION_V385_FAIR_REFRESH marker=20260907-kraken-coverage-truth-fairness-v385 "\n            "account=%s ready=%s reason=%s round_robin=true bounded_startup_adopter=true "\n            "read_only_snapshot=true snapshot_ttl_unchanged=true retry_interval_unchanged=true "\n            "synthetic_success=false exits_preserved=true user_entries_fail_closed_until_ready=true",\n            account, str(refreshed).lower(), refreshed_reason,\n        )\n        return f"{account}:{'ready' if refreshed else refreshed_reason}"\n    finally:\n        _USER_REFRESH_LOCK.release()\n\n\n_refresh_one_user = _refresh_one_user_v385\n'''
    text = text.replace(anchor, fair_patch + anchor, 1)
    V285.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    changed_v366 = patch_v366()
    changed_v285 = patch_v285()
    print(
        "KRAKEN_COVERAGE_TRUTH_FAIRNESS_V385_PATCH_APPLIED "
        f"marker={MARKER} v366_changed={changed_v366} v285_changed={changed_v285} "
        "pre_v371_false_telemetry_removed=true user_refresh_round_robin=true "
        "snapshot_ttl_unchanged=true retry_interval_unchanged=true rate_limits_unchanged=true "
        "orders_submitted=false protection_fabricated=false readiness_fabricated=false "
        "safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
