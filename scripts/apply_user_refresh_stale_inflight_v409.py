#!/usr/bin/env python3
"""Patch v390 user-position refresh with bounded stale-flight recovery (v409).

A v390 account refresh may block inside an authenticated Kraken read. Because
v390 records only a set membership, that account can remain inflight forever and
its authoritative snapshot can age indefinitely. v409 adds a started-at clock,
one hard-saturation escape per authoritative snapshot generation, and a flight
token so a late retired worker cannot clear ownership of a newer worker.

This is liveness only. Snapshot TTL, authenticated-read/rate/nonce ordering,
position/cost-basis/protection truth, writer authority, capital/risk/kill-switch,
order/fill gates and user-entry fail-closed behavior are unchanged.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "runtime_authoritative_position_coverage_v285_patch.py"
MARKER = "20260909-user-refresh-stale-inflight-v409"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "AUTHORITATIVE_USER_POSITION_V409_STALE_FLIGHT_RETIRED" in text:
        print(f"USER_REFRESH_STALE_INFLIGHT_V409_ALREADY_APPLIED marker={MARKER}")
        return

    anchor = '_USER_COST_BASIS_WAKE_EPOCH_V390: dict[str, int] = {}\n'
    if anchor not in text:
        raise RuntimeError("v409 expected v390 state anchor missing")
    text = text.replace(
        anchor,
        anchor
        + '_USER_REFRESH_STARTED_V409: dict[str, float] = {}\n'
        + '_USER_REFRESH_TOKEN_V409: dict[str, int] = {}\n'
        + '_USER_REFRESH_ESCAPE_GENERATION_V409: dict[str, int] = {}\n\n'
        + 'def _user_refresh_hard_timeout_v409() -> float:\n'
        + '    return max(120.0, _snapshot_max_age_s() * 2.0)\n\n'
        + 'def _retire_stale_user_refresh_v409(manager: Any) -> int:\n'
        + '    expected = _expected_accounts(manager)\n'
        + '    now = time.monotonic()\n'
        + '    hard_s = _user_refresh_hard_timeout_v409()\n'
        + '    retired = 0\n'
        + '    with _USER_REFRESH_INFLIGHT_LOCK_V390:\n'
        + '        for account in tuple(_USER_REFRESH_INFLIGHT_V390):\n'
        + '            started = float(_USER_REFRESH_STARTED_V409.get(account, 0.0) or 0.0)\n'
        + '            if started <= 0.0 or now - started < hard_s:\n'
        + '                continue\n'
        + '            broker = expected.get(account)\n'
        + '            try:\n'
        + '                generation = int(getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0)\n'
        + '            except Exception:\n'
        + '                generation = 0\n'
        + '            if _USER_REFRESH_ESCAPE_GENERATION_V409.get(account) == generation:\n'
        + '                continue\n'
        + '            _USER_REFRESH_ESCAPE_GENERATION_V409[account] = generation\n'
        + '            _USER_REFRESH_INFLIGHT_V390.discard(account)\n'
        + '            _USER_REFRESH_STARTED_V409.pop(account, None)\n'
        + '            retired += 1\n'
        + '            LOGGER.critical(\n'
        + '                "AUTHORITATIVE_USER_POSITION_V409_STALE_FLIGHT_RETIRED marker=20260909-user-refresh-stale-inflight-v409 "\n'
        + '                "account=%s age_s=%.1f hard_timeout_s=%.1f snapshot_generation=%d "\n'
        + '                "one_escape_per_generation=true readiness_granted=false snapshot_ttl_unchanged=true "\n'
        + '                "synthetic_success=false orders_submitted=false safety_gates_bypassed=false",\n'
        + '                account, now - started, hard_s, generation,\n'
        + '            )\n'
        + '    return retired\n\n',
        1,
    )

    old_sig = '''def _run_user_refresh_v390(\n    manager: Any,\n    account: str,\n    broker: Any,\n    prior_reason: str,\n    prior_snapshot_reason: str,\n    connected_users: int,\n    safe_interval: float,\n    ttl: float,\n) -> None:\n'''
    new_sig = '''def _run_user_refresh_v390(\n    manager: Any,\n    account: str,\n    broker: Any,\n    prior_reason: str,\n    prior_snapshot_reason: str,\n    connected_users: int,\n    safe_interval: float,\n    ttl: float,\n    flight_token: int,\n) -> None:\n'''
    if old_sig not in text:
        raise RuntimeError("v409 v390 worker signature anchor missing")
    text = text.replace(old_sig, new_sig, 1)

    old_finally = '''    finally:\n        with _USER_REFRESH_INFLIGHT_LOCK_V390:\n            _USER_REFRESH_INFLIGHT_V390.discard(account)\n\n\ndef _refresh_one_user_v390(manager: Any) -> str:\n    candidate, connected_users, safe_interval, ttl = _user_refresh_candidate_v390(manager)\n'''
    new_finally = '''    finally:\n        with _USER_REFRESH_INFLIGHT_LOCK_V390:\n            if int(_USER_REFRESH_TOKEN_V409.get(account, 0) or 0) == int(flight_token):\n                _USER_REFRESH_INFLIGHT_V390.discard(account)\n                _USER_REFRESH_STARTED_V409.pop(account, None)\n            else:\n                LOGGER.info(\n                    "AUTHORITATIVE_USER_POSITION_V409_LATE_WORKER_FENCED marker=20260909-user-refresh-stale-inflight-v409 "\n                    "account=%s retired_token=%d current_token=%d newer_owner_preserved=true readiness_granted=false",\n                    account, flight_token, int(_USER_REFRESH_TOKEN_V409.get(account, 0) or 0),\n                )\n\n\ndef _refresh_one_user_v390(manager: Any) -> str:\n    _retire_stale_user_refresh_v409(manager)\n    candidate, connected_users, safe_interval, ttl = _user_refresh_candidate_v390(manager)\n'''
    if old_finally not in text:
        raise RuntimeError("v409 v390 finally/dispatch anchor missing")
    text = text.replace(old_finally, new_finally, 1)

    old_claim = '''    with _USER_REFRESH_INFLIGHT_LOCK_V390:\n        if account in _USER_REFRESH_INFLIGHT_V390:\n            return f"{account}:refresh_inflight"\n        _USER_REFRESH_INFLIGHT_V390.add(account)\n\n    thread = threading.Thread(\n'''
    new_claim = '''    with _USER_REFRESH_INFLIGHT_LOCK_V390:\n        if account in _USER_REFRESH_INFLIGHT_V390:\n            return f"{account}:refresh_inflight"\n        flight_token = int(_USER_REFRESH_TOKEN_V409.get(account, 0) or 0) + 1\n        _USER_REFRESH_TOKEN_V409[account] = flight_token\n        _USER_REFRESH_STARTED_V409[account] = time.monotonic()\n        _USER_REFRESH_INFLIGHT_V390.add(account)\n\n    thread = threading.Thread(\n'''
    if old_claim not in text:
        raise RuntimeError("v409 v390 claim anchor missing")
    text = text.replace(old_claim, new_claim, 1)

    old_args = '''            manager, account, broker, prior_reason, prior_snapshot_reason,\n            connected_users, safe_interval, ttl,\n        ),\n'''
    new_args = '''            manager, account, broker, prior_reason, prior_snapshot_reason,\n            connected_users, safe_interval, ttl, flight_token,\n        ),\n'''
    if old_args not in text:
        raise RuntimeError("v409 v390 thread args anchor missing")
    text = text.replace(old_args, new_args, 1)

    old_log = '        "account=%s connected_users=%d per_account_single_flight=true other_users_not_blocked=true "\\n\n'
    new_log = '        "account=%s connected_users=%d per_account_single_flight=true stale_flight_recovery_v409=true other_users_not_blocked=true "\\n\n'
    if old_log in text:
        text = text.replace(old_log, new_log, 1)

    TARGET.write_text(text, encoding="utf-8")
    print(
        f"USER_REFRESH_STALE_INFLIGHT_V409_PATCH_APPLIED marker={MARKER} "
        "per_account_started_at=true token_fence=true one_escape_per_snapshot_generation=true "
        "snapshot_ttl_unchanged=true readiness_fabricated=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
