#!/usr/bin/env python3
"""Apply fail-closed NIJA user readiness deadline convergence v390.

This build-time source patch closes two user-account liveness gaps without
weakening any readiness proof:

1. v385's fair user refresh is upgraded from pure round-robin timing to an
   oldest-snapshot/deadline-aware selector. With multiple connected users, a
   successful user's next refresh is scheduled early enough that serialized
   Kraken reads can complete before the unchanged v285 authoritative snapshot
   TTL expires. Unready users retain the existing bounded retry cadence.
2. When v288/v304 finishes a genuine authenticated bulk cost-basis flight for a
   user account, that account is marked *due for read-only reconciliation* on
   the next v285 monitor pulse. The completed history result does not grant
   readiness or mutate a position; the existing startup adopter must still
   consume it and pass every cost-basis, quantity, position, protection and
   eligibility check.

The authoritative snapshot TTL is unchanged. Kraken rate limits, credential
serialization, nonce ordering, writer authority, capital, risk, kill switch,
minimum order, execution proof, order/fill confirmation and protective-exit
requirements are unchanged. No order is submitted and no balance, position,
cost basis, protection, execution proof or eligibility is fabricated.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V285 = ROOT / "bot" / "runtime_authoritative_position_coverage_v285_patch.py"
V288 = ROOT / "bot" / "runtime_kraken_cost_basis_bulk_v288_patch.py"
MARKER = "20260907-user-readiness-deadline-convergence-v390"


def patch_v285() -> bool:
    text = V285.read_text(encoding="utf-8")
    if "AUTHORITATIVE_USER_POSITION_V390_DEADLINE_REFRESH" in text:
        return False

    start_marker = "# v385: fairness-only replacement for the single-user refresh selector."
    end_marker = "_refresh_one_user = _refresh_one_user_v385\n"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise RuntimeError("v390 expected v385 user-refresh block not found")
    end += len(end_marker)

    replacement = '''# v390: deadline-aware fairness for connected user authoritative snapshots.\n# The 90-second (or configured) authoritative snapshot TTL is unchanged.\n# Successful users are refreshed early enough for serialized multi-user Kraken\n# reads to stay inside that TTL; unready users retain the existing retry delay.\n_USER_REFRESH_LAST_ACCOUNT_V390 = ""\n\n\ndef _user_refresh_safe_interval_v390(user_count: int) -> float:\n    ttl = _snapshot_max_age_s()\n    count = max(1, int(user_count or 1))\n    # Reserve one serialized-refresh slot of headroom.  This changes only when\n    # a genuine authenticated refresh is attempted, never what counts as fresh.\n    deadline_share = ttl / float(count + 1)\n    return max(10.0, min(_refresh_interval_s(), deadline_share))\n\n\ndef _refresh_one_user_v390(manager: Any) -> str:\n    global _USER_REFRESH_LAST_ACCOUNT_V390\n    expected = _expected_accounts(manager)\n    now = time.monotonic()\n    users = [\n        (str(account), broker)\n        for account, broker in expected.items()\n        if str(account).startswith("user:") and broker is not None and _connected(broker)\n    ]\n    users.sort(key=lambda item: item[0])\n    if not users:\n        return "no_user_refresh_needed"\n\n    safe_interval = _user_refresh_safe_interval_v390(len(users))\n    ttl = _snapshot_max_age_s()\n    candidates = []\n    for account, broker in users:\n        ready, reason = _strong_broker_proof(broker)\n        snapshot_ok, snapshot_reason, _rows, age_s, _generation = _snapshot_status(broker)\n        due_at = float(_USER_NEXT_REFRESH.get(account, 0.0) or 0.0)\n        due = now >= due_at\n        try:\n            age = float(age_s)\n        except Exception:\n            age = float("inf")\n        # A ready user may be pulled forward as its genuine snapshot approaches\n        # the multi-user refresh deadline. An unready user still honors retry_s.\n        near_deadline = bool(ready and age >= safe_interval)\n        if not due and not near_deadline:\n            continue\n        age_score = (ttl * 2.0) if age == float("inf") else max(0.0, age)\n        candidates.append((age_score, 0 if ready else 1, account, broker, reason, snapshot_reason))\n\n    if not candidates:\n        return "no_user_refresh_needed"\n\n    # Oldest genuine snapshot first. For equal age, an unready account wins.\n    candidates.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)\n    _age_score, _unready, account, broker, prior_reason, prior_snapshot_reason = candidates[0]\n\n    if not _USER_REFRESH_LOCK.acquire(blocking=False):\n        return "user_refresh_busy"\n    try:\n        try:\n            sync = importlib.import_module("bot.startup_position_sync")\n            adopter = getattr(sync, "_adopt_broker_positions", None)\n            eps_getter = getattr(sync, "_get_entry_price_store", None)\n            if not callable(adopter):\n                _USER_NEXT_REFRESH[account] = now + _retry_s()\n                _USER_REFRESH_LAST_ACCOUNT_V390 = account\n                return f"{account}:adopter_missing"\n            eps = eps_getter() if callable(eps_getter) else None\n            adopter(broker, account, eps)\n        except Exception as exc:\n            _USER_NEXT_REFRESH[account] = time.monotonic() + _retry_s()\n            _USER_REFRESH_LAST_ACCOUNT_V390 = account\n            LOGGER.warning(\n                "AUTHORITATIVE_USER_POSITION_V390_DEADLINE_REFRESH_FAILED marker=20260907-user-readiness-deadline-convergence-v390 "\n                "account=%s prior_reason=%s prior_snapshot_reason=%s error=%s:%s fail_closed=true "\n                "oldest_snapshot_first=true snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true "\n                "readiness_fabricated=false eligibility_fabricated=false",\n                account, prior_reason, prior_snapshot_reason, type(exc).__name__, exc,\n            )\n            return f"{account}:refresh_exception"\n\n        refreshed, refreshed_reason = _strong_broker_proof(broker)\n        next_delay = safe_interval if refreshed else _retry_s()\n        _USER_NEXT_REFRESH[account] = time.monotonic() + next_delay\n        _USER_REFRESH_LAST_ACCOUNT_V390 = account\n        log = LOGGER.critical if refreshed else LOGGER.warning\n        log(\n            "AUTHORITATIVE_USER_POSITION_V390_DEADLINE_REFRESH marker=20260907-user-readiness-deadline-convergence-v390 "\n            "account=%s ready=%s reason=%s connected_users=%d next_delay_s=%.1f snapshot_ttl_s=%.1f "\n            "oldest_snapshot_first=true bounded_startup_adopter=true read_only_snapshot=true "\n            "snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true synthetic_success=false "\n            "eligibility_fabricated=false exits_preserved=true user_entries_fail_closed_until_ready=true",\n            account, str(refreshed).lower(), refreshed_reason, len(users), next_delay, ttl,\n        )\n        return f"{account}:{'ready' if refreshed else refreshed_reason}"\n    finally:\n        _USER_REFRESH_LOCK.release()\n\n\n_refresh_one_user = _refresh_one_user_v390\n'''

    text = text[:start] + replacement + text[end:]
    V285.write_text(text, encoding="utf-8")
    return True


def patch_v288() -> bool:
    text = V288.read_text(encoding="utf-8")
    if "KRAKEN_COST_BASIS_V390_USER_RECONCILE_DUE" in text:
        return False

    anchor = "\ndef _finish_bulk_flight(flight: dict[str, Any], method: Any, symbols: tuple[str, ...]) -> None:\n"
    if anchor not in text:
        raise RuntimeError("v390 v288 finish-flight anchor missing")

    helper = '''\ndef _wake_user_reconcile_after_bulk_v390(method: Any, result: Any) -> None:\n    """Mark only a user account due after genuine positive history completes."""\n    if not isinstance(result, Mapping):\n        return\n    positive = {\n        str(key or "").strip().upper(): _float(value)\n        for key, value in result.items()\n        if str(key or "").strip() and _float(value) > 0.0\n    }\n    if not positive:\n        return\n    real = getattr(method, "__self__", None)\n    account_id = str(getattr(real, "account_identifier", "") or "").strip()\n    if not account_id.upper().startswith("USER:"):\n        return\n    user_name = account_id.split(":", 1)[1].strip().lower()\n    if not user_name:\n        return\n    try:\n        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")\n        due_map = getattr(v285, "_USER_NEXT_REFRESH", None)\n        if not isinstance(due_map, dict):\n            return\n        account_key = f"user:{user_name}:kraken"\n        due_map[account_key] = 0.0\n        LOGGER.critical(\n            "KRAKEN_COST_BASIS_V390_USER_RECONCILE_DUE marker=20260907-user-readiness-deadline-convergence-v390 "\n            "account=%s recovered_symbols=%s due_only=true authenticated_history_result_required=true "\n            "readiness_granted=false eligibility_granted=false position_mutated=false cost_basis_fabricated=false "\n            "snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true safety_gates_bypassed=false",\n            account_key, ",".join(sorted(positive)),\n        )\n    except Exception:\n        LOGGER.debug("v390 user reconciliation wake deferred", exc_info=True)\n\n\n'''
    text = text.replace(anchor, helper + anchor, 1)

    old = '''        flight["result"] = {\n            str(key or "").strip().upper(): _float(value)\n            for key, value in result.items()\n            if str(key or "").strip() and _float(value) > 0.0\n        }\n'''
    new = '''        flight["result"] = {\n            str(key or "").strip().upper(): _float(value)\n            for key, value in result.items()\n            if str(key or "").strip() and _float(value) > 0.0\n        }\n        _wake_user_reconcile_after_bulk_v390(method, flight["result"])\n'''
    if old not in text:
        raise RuntimeError("v390 v288 result anchor missing")
    text = text.replace(old, new, 1)
    V288.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    changed_v285 = patch_v285()
    changed_v288 = patch_v288()
    print(
        "USER_READINESS_DEADLINE_CONVERGENCE_V390_PATCH_APPLIED "
        f"marker={MARKER} v285_changed={changed_v285} v288_changed={changed_v288} "
        "oldest_snapshot_first=true multi_user_deadline_budget=true completed_history_wakes_reconcile=true "
        "snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true retry_fail_closed=true "
        "orders_submitted=false cost_basis_fabricated=false readiness_fabricated=false "
        "eligibility_fabricated=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
