#!/usr/bin/env python3
"""Patch user refresh liveness v409 and v88 supervision convergence v412.

v409 bounds a stuck per-user refresh and fences retired workers. v412 repairs a
separate production liveness defect: the v88 convergence monitor used to exit as
soon as the trading-state patch loaded, even when the Kraken supervision chain
(v86..v374..v303) was still incomplete. That could leave rebuilt user brokers
without canonical identity convergence and strand user readiness after a restart.

Both changes are liveness-only. Snapshot TTL, authenticated read/rate/nonce
ordering, writer authority, capital/risk/kill-switch, protective exits,
execution/order/fill gates, and user-entry fail-closed behavior are unchanged.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "runtime_authoritative_position_coverage_v285_patch.py"
V88 = ROOT / "bot" / "production_runtime_convergence_v88_patch.py"
MARKER = "20260909-user-refresh-stale-inflight-v409"
V412_MARKER = "20260914-v88-kraken-supervision-monitor-v412"


def _patch_v409() -> bool:
    text = TARGET.read_text(encoding="utf-8")
    if "AUTHORITATIVE_USER_POSITION_V409_STALE_FLIGHT_RETIRED" in text:
        print(f"USER_REFRESH_STALE_INFLIGHT_V409_ALREADY_APPLIED marker={MARKER}")
        return False

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
    return True


def _patch_v412() -> bool:
    text = V88.read_text(encoding="utf-8")
    if V412_MARKER in text:
        print(f"V88_KRAKEN_SUPERVISION_MONITOR_V412_ALREADY_APPLIED marker={V412_MARKER}")
        return False

    old_monitor = '''def _monitor() -> None:\n    deadline = time.monotonic() + 600.0\n    while time.monotonic() < deadline:\n        _install_kraken_user_supervision()\n        if _try_patch_loaded():\n            return\n        time.sleep(0.25)\n    LOGGER.warning("PRODUCTION_RUNTIME_CONVERGENCE_V88_MONITOR_EXPIRED marker=%s", MARKER)\n'''
    new_monitor = '''def _monitor() -> None:\n    deadline = time.monotonic() + 600.0\n    last_state = None\n    kraken_ready = False\n    tsm_ready = False\n    while time.monotonic() < deadline:\n        kraken_ready = bool(_install_kraken_user_supervision())\n        tsm_ready = bool(_try_patch_loaded())\n        state = (kraken_ready, tsm_ready)\n        if state != last_state:\n            LOGGER.info(\n                "PRODUCTION_RUNTIME_CONVERGENCE_V412_WAIT marker=20260914-v88-kraken-supervision-monitor-v412 "\n                "kraken_supervision_ready=%s trading_state_patch_ready=%s monitor_requires_both=true "\n                "safety_gates_bypassed=false",\n                str(kraken_ready).lower(), str(tsm_ready).lower(),\n            )\n            last_state = state\n        if kraken_ready and tsm_ready:\n            LOGGER.critical(\n                "PRODUCTION_RUNTIME_CONVERGENCE_V412_READY marker=20260914-v88-kraken-supervision-monitor-v412 "\n                "kraken_supervision_ready=true trading_state_patch_ready=true monitor_requires_both=true "\n                "safety_gates_bypassed=false"\n            )\n            return\n        time.sleep(0.25)\n    LOGGER.warning(\n        "PRODUCTION_RUNTIME_CONVERGENCE_V88_MONITOR_EXPIRED marker=%s "\n        "kraken_supervision_ready=%s trading_state_patch_ready=%s monitor_requires_both=true "\n        "safety_gates_bypassed=false",\n        MARKER, str(kraken_ready).lower(), str(tsm_ready).lower(),\n    )\n'''
    if old_monitor not in text:
        raise RuntimeError("v412 expected v88 monitor anchor missing")
    text = text.replace(old_monitor, new_monitor, 1)

    # v421 starts the critical Kraken liveness thread between the stale-log
    # filter and these two synchronous convergence calls. Match only the unique
    # call pair so v412 can add truthful readiness telemetry without moving or
    # delaying the V420 monitor. This also remains compatible with the older
    # pre-v421 layout where the same pair immediately followed the log filter.
    old_install_calls = '''    _install_kraken_user_supervision()\n    _try_patch_loaded()\n'''
    new_install_calls = '''    kraken_ready = bool(_install_kraken_user_supervision())\n    tsm_ready = bool(_try_patch_loaded())\n'''
    if text.count(old_install_calls) != 1:
        raise RuntimeError("v412 expected one v88 install call-pair anchor")
    text = text.replace(old_install_calls, new_install_calls, 1)

    old_log = '''        "PRODUCTION_RUNTIME_CONVERGENCE_V88_INSTALLED marker=%s circuit_classification=true "\n        "kraken_user_supervision=true kraken_user_rebuild_v90=true all_account_connectivity_v266=true "\n'''
    new_log = '''        "PRODUCTION_RUNTIME_CONVERGENCE_V88_INSTALLED marker=%s circuit_classification_ready=%s "\n        "kraken_user_supervision_ready=%s v412_monitor_requires_both=true "\n        "kraken_user_rebuild_v90=true all_account_connectivity_v266=true "\n'''
    if old_log not in text:
        raise RuntimeError("v412 expected v88 install log anchor missing")
    text = text.replace(old_log, new_log, 1)

    old_tail = '''        MARKER,\n    )\n    return True\n'''
    new_tail = '''        MARKER, str(tsm_ready).lower(), str(kraken_ready).lower(),\n    )\n    return True\n'''
    if old_tail not in text:
        raise RuntimeError("v412 expected v88 log args anchor missing")
    text = text.replace(old_tail, new_tail, 1)

    V88.write_text(text, encoding="utf-8")
    print(
        f"V88_KRAKEN_SUPERVISION_MONITOR_V412_PATCH_APPLIED marker={V412_MARKER} "
        "monitor_requires_kraken_and_tsm=true startup_truthful_telemetry=true "
        "v421_critical_monitor_order_preserved=true "
        "snapshot_ttl_unchanged=true readiness_fabricated=false safety_gates_bypassed=false"
    )
    return True


def main() -> None:
    _patch_v409()
    _patch_v412()


if __name__ == "__main__":
    main()
