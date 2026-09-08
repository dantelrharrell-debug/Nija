#!/usr/bin/env python3
"""Apply fail-closed NIJA user readiness deadline convergence v390/v408.

This build-time source patch closes user-account liveness gaps without weakening
any readiness proof:

1. v385's fair user refresh is upgraded from pure round-robin timing to an
   oldest-snapshot/deadline-aware selector. With multiple connected users, a
   successful user's next refresh is scheduled early enough to complete before
   the unchanged v285 authoritative snapshot TTL expires.
2. User reconciliation is dispatched per account instead of holding one global
   user-refresh lock around a potentially long authenticated history recovery.
   One slow account therefore cannot starve another account past its freshness
   deadline. Same-account duplicate refreshes remain single-flight.
3. When v288/v304 finishes a genuine authenticated bulk cost-basis flight for a
   user account, that account is marked *due for read-only reconciliation* on
   the next v285 monitor pulse. The completed history result does not grant
   readiness or mutate a position; the existing startup adopter must still
   consume it and pass every cost-basis, quantity, position, protection and
   eligibility check.
4. v408 makes that authenticated-history wake generation-aware. If history
   finishes while the same account's adopter is still running, the adopter may
   not overwrite the new "due now" wake with its ordinary retry delay. This
   closes the observed lost-wake race without extending cache/snapshot TTLs or
   accepting stale/synthetic cost basis.

The authoritative snapshot TTL is unchanged. Kraken rate limits, authenticated
read serialization, nonce ordering, writer authority, capital, risk, kill
switch, minimum order, execution proof, order/fill confirmation and
protective-exit requirements are unchanged. No order is submitted and no
balance, position, cost basis, protection, execution proof or eligibility is
fabricated.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V285 = ROOT / "bot" / "runtime_authoritative_position_coverage_v285_patch.py"
V288 = ROOT / "bot" / "runtime_kraken_cost_basis_bulk_v288_patch.py"
MARKER = "20260907-user-readiness-deadline-convergence-v390"
V408_MARKER = "20260908-user-cost-basis-adoption-wake-v408"


def patch_v285() -> bool:
    text = V285.read_text(encoding="utf-8")
    if "AUTHORITATIVE_USER_POSITION_V390_NONBLOCKING_DISPATCH" in text:
        return False

    start_marker = "# v385: fairness-only replacement for the single-user refresh selector."
    end_marker = "_refresh_one_user = _refresh_one_user_v385\n"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise RuntimeError("v390 expected v385 user-refresh block not found")
    end += len(end_marker)

    replacement = '''# v390/v408: deadline-aware, per-account nonblocking fairness for connected users.\n# The authoritative snapshot TTL is unchanged. Different user accounts may\n# reconcile concurrently, while each account remains single-flight. Kraken's\n# existing authenticated-read/rate/nonce serialization remains authoritative.\n# v408 preserves a genuine authenticated-history wake that arrives while an\n# adopter is already in flight, preventing the completion path from replacing\n# that wake with an ordinary retry delay.\n_USER_REFRESH_LAST_ACCOUNT_V390 = ""\n_USER_REFRESH_INFLIGHT_V390: set[str] = set()\n_USER_REFRESH_INFLIGHT_LOCK_V390 = threading.RLock()\n_USER_COST_BASIS_WAKE_EPOCH_V390: dict[str, int] = {}\n\n\ndef _user_refresh_safe_interval_v390(user_count: int) -> float:\n    ttl = _snapshot_max_age_s()\n    count = max(1, int(user_count or 1))\n    # Reserve one serialized-refresh slot of headroom. This changes only when\n    # a genuine authenticated refresh is attempted, never what counts as fresh.\n    deadline_share = ttl / float(count + 1)\n    return max(10.0, min(_refresh_interval_s(), deadline_share))\n\n\ndef _user_refresh_candidate_v390(manager: Any):\n    expected = _expected_accounts(manager)\n    now = time.monotonic()\n    users = [\n        (str(account), broker)\n        for account, broker in expected.items()\n        if str(account).startswith("user:") and broker is not None and _connected(broker)\n    ]\n    users.sort(key=lambda item: item[0])\n    if not users:\n        return None, 0, 0.0, 0.0\n\n    safe_interval = _user_refresh_safe_interval_v390(len(users))\n    ttl = _snapshot_max_age_s()\n    with _USER_REFRESH_INFLIGHT_LOCK_V390:\n        inflight = set(_USER_REFRESH_INFLIGHT_V390)\n\n    candidates = []\n    for account, broker in users:\n        if account in inflight:\n            continue\n        ready, reason = _strong_broker_proof(broker)\n        _snapshot_ok, snapshot_reason, _rows, age_s, _generation = _snapshot_status(broker)\n        due_at = float(_USER_NEXT_REFRESH.get(account, 0.0) or 0.0)\n        due = now >= due_at\n        try:\n            age = float(age_s)\n        except Exception:\n            age = float("inf")\n        # A ready user is pulled forward as its genuine snapshot approaches the\n        # multi-user deadline. An unready user still honors the existing retry.\n        near_deadline = bool(ready and age >= safe_interval)\n        if not due and not near_deadline:\n            continue\n        age_score = (ttl * 2.0) if age == float("inf") else max(0.0, age)\n        # Oldest snapshot first. If age ties, an unready account gets priority.\n        candidates.append((age_score, 0 if ready else 1, account, broker, reason, snapshot_reason))\n\n    if not candidates:\n        return None, len(users), safe_interval, ttl\n    candidates.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)\n    return candidates[0], len(users), safe_interval, ttl\n\n\ndef _run_user_refresh_v390(\n    manager: Any,\n    account: str,\n    broker: Any,\n    prior_reason: str,\n    prior_snapshot_reason: str,\n    connected_users: int,\n    safe_interval: float,\n    ttl: float,\n) -> None:\n    global _USER_REFRESH_LAST_ACCOUNT_V390\n    wake_epoch_before = int(_USER_COST_BASIS_WAKE_EPOCH_V390.get(account, 0) or 0)\n    try:\n        try:\n            sync = importlib.import_module("bot.startup_position_sync")\n            adopter = getattr(sync, "_adopt_broker_positions", None)\n            eps_getter = getattr(sync, "_get_entry_price_store", None)\n            if not callable(adopter):\n                _USER_NEXT_REFRESH[account] = time.monotonic() + _retry_s()\n                _USER_REFRESH_LAST_ACCOUNT_V390 = account\n                LOGGER.warning(\n                    "AUTHORITATIVE_USER_POSITION_V390_DEADLINE_REFRESH_FAILED marker=20260907-user-readiness-deadline-convergence-v390 "\n                    "account=%s reason=adopter_missing fail_closed=true readiness_fabricated=false",\n                    account,\n                )\n                return\n            eps = eps_getter() if callable(eps_getter) else None\n            adopter(broker, account, eps)\n        except Exception as exc:\n            # A genuine history completion that occurred during this adopter must\n            # still get an immediate follow-up even if this pass itself failed.\n            wake_epoch_after = int(_USER_COST_BASIS_WAKE_EPOCH_V390.get(account, 0) or 0)\n            if wake_epoch_after != wake_epoch_before:\n                _USER_NEXT_REFRESH[account] = 0.0\n            else:\n                _USER_NEXT_REFRESH[account] = time.monotonic() + _retry_s()\n            _USER_REFRESH_LAST_ACCOUNT_V390 = account\n            LOGGER.warning(\n                "AUTHORITATIVE_USER_POSITION_V390_DEADLINE_REFRESH_FAILED marker=20260907-user-readiness-deadline-convergence-v390 "\n                "account=%s prior_reason=%s prior_snapshot_reason=%s error=%s:%s fail_closed=true "\n                "history_wake_preserved=%s per_account_single_flight=true snapshot_ttl_unchanged=true "\n                "kraken_rate_limits_unchanged=true readiness_fabricated=false eligibility_fabricated=false",\n                account, prior_reason, prior_snapshot_reason, type(exc).__name__, exc,\n                str(wake_epoch_after != wake_epoch_before).lower(),\n            )\n            return\n\n        refreshed, refreshed_reason = _strong_broker_proof(broker)\n        wake_epoch_after = int(_USER_COST_BASIS_WAKE_EPOCH_V390.get(account, 0) or 0)\n        history_wake_preserved = bool(wake_epoch_after != wake_epoch_before)\n        if history_wake_preserved:\n            # The authenticated history result completed after this adopter began,\n            # so this pass could not be assumed to have consumed it. Keep the\n            # account immediately due. No freshness/readiness is granted here.\n            _USER_NEXT_REFRESH[account] = 0.0\n            next_delay = 0.0\n        else:\n            next_delay = safe_interval if refreshed else _retry_s()\n            _USER_NEXT_REFRESH[account] = time.monotonic() + next_delay\n        _USER_REFRESH_LAST_ACCOUNT_V390 = account\n        log = LOGGER.critical if refreshed else LOGGER.warning\n        log(\n            "AUTHORITATIVE_USER_POSITION_V390_DEADLINE_REFRESH marker=20260907-user-readiness-deadline-convergence-v390 "\n            "account=%s ready=%s reason=%s connected_users=%d next_delay_s=%.1f snapshot_ttl_s=%.1f "\n            "history_wake_preserved=%s v408_lost_wake_closed=true oldest_snapshot_first=true "\n            "per_account_single_flight=true nonblocking_other_users=true bounded_startup_adopter=true "\n            "read_only_snapshot=true snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true "\n            "synthetic_success=false eligibility_fabricated=false exits_preserved=true "\n            "user_entries_fail_closed_until_ready=true",\n            account, str(refreshed).lower(), refreshed_reason, connected_users, next_delay, ttl,\n            str(history_wake_preserved).lower(),\n        )\n    finally:\n        with _USER_REFRESH_INFLIGHT_LOCK_V390:\n            _USER_REFRESH_INFLIGHT_V390.discard(account)\n\n\ndef _refresh_one_user_v390(manager: Any) -> str:\n    candidate, connected_users, safe_interval, ttl = _user_refresh_candidate_v390(manager)\n    if candidate is None:\n        with _USER_REFRESH_INFLIGHT_LOCK_V390:\n            active = len(_USER_REFRESH_INFLIGHT_V390)\n        return "user_refresh_inflight" if active else "no_user_refresh_needed"\n\n    _age_score, _unready, account, broker, prior_reason, prior_snapshot_reason = candidate\n    with _USER_REFRESH_INFLIGHT_LOCK_V390:\n        if account in _USER_REFRESH_INFLIGHT_V390:\n            return f"{account}:refresh_inflight"\n        _USER_REFRESH_INFLIGHT_V390.add(account)\n\n    thread = threading.Thread(\n        target=_run_user_refresh_v390,\n        args=(\n            manager, account, broker, prior_reason, prior_snapshot_reason,\n            connected_users, safe_interval, ttl,\n        ),\n        name=f"AuthoritativeUserRefreshV390-{account}",\n        daemon=True,\n    )\n    thread.start()\n    LOGGER.info(\n        "AUTHORITATIVE_USER_POSITION_V390_NONBLOCKING_DISPATCH marker=20260907-user-readiness-deadline-convergence-v390 "\n        "account=%s connected_users=%d per_account_single_flight=true other_users_not_blocked=true "\n        "authenticated_adopter_only=true snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true "\n        "nonce_ordering_unchanged=true readiness_granted=false eligibility_granted=false orders_submitted=false",\n        account, connected_users,\n    )\n    return f"{account}:refresh_dispatched"\n\n\n_refresh_one_user = _refresh_one_user_v390\n'''

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

    helper = '''\ndef _wake_user_reconcile_after_bulk_v390(method: Any, result: Any) -> None:\n    """Mark only a user account due after genuine positive history completes."""\n    if not isinstance(result, Mapping):\n        return\n    positive = {\n        str(key or "").strip().upper(): _float(value)\n        for key, value in result.items()\n        if str(key or "").strip() and _float(value) > 0.0\n    }\n    if not positive:\n        return\n    real = getattr(method, "__self__", None)\n    account_id = str(getattr(real, "account_identifier", "") or "").strip()\n    if not account_id.upper().startswith("USER:"):\n        return\n    user_name = account_id.split(":", 1)[1].strip().lower()\n    if not user_name:\n        return\n    try:\n        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")\n        due_map = getattr(v285, "_USER_NEXT_REFRESH", None)\n        wake_epochs = getattr(v285, "_USER_COST_BASIS_WAKE_EPOCH_V390", None)\n        if not isinstance(due_map, dict) or not isinstance(wake_epochs, dict):\n            return\n        account_key = f"user:{user_name}:kraken"\n        wake_epochs[account_key] = int(wake_epochs.get(account_key, 0) or 0) + 1\n        due_map[account_key] = 0.0\n        LOGGER.critical(\n            "KRAKEN_COST_BASIS_V390_USER_RECONCILE_DUE marker=20260907-user-readiness-deadline-convergence-v390 "\n            "account=%s recovered_symbols=%s due_only=true authenticated_history_result_required=true "\n            "wake_epoch=%d v408_lost_wake_closed=true readiness_granted=false eligibility_granted=false "\n            "position_mutated=false cost_basis_fabricated=false snapshot_ttl_unchanged=true "\n            "kraken_rate_limits_unchanged=true safety_gates_bypassed=false",\n            account_key, ",".join(sorted(positive)), wake_epochs[account_key],\n        )\n    except Exception:\n        LOGGER.debug("v390/v408 user reconciliation wake deferred", exc_info=True)\n\n\n'''
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
        f"marker={MARKER} v408_marker={V408_MARKER} v285_changed={changed_v285} v288_changed={changed_v288} "
        "oldest_snapshot_first=true multi_user_deadline_budget=true per_account_nonblocking=true "
        "same_account_single_flight=true completed_history_wakes_reconcile=true "
        "lost_history_wake_preserved=true history_wake_epoch=true snapshot_ttl_unchanged=true "
        "kraken_rate_limits_unchanged=true nonce_ordering_unchanged=true retry_fail_closed=true "
        "orders_submitted=false cost_basis_fabricated=false readiness_fabricated=false "
        "eligibility_fabricated=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
