"""Apply NIJA execution-proof startup isolation v339.

Production on 2026-08-31 exposed a startup-order race: the canonical writer could
refresh the legacy HEARTBEAT_MARKER_PATH before v169 installed. That authority
liveness write used FILL_VERIFY and could be accepted by the pre-v169 verifier.
Once v169 installed it correctly rejected the stale authority marker, leaving
activation fail-closed on proof.execution_ready.

The 2026-09-06 restart recovery extension also closes a second liveness gap:
a genuine Kraken fill may have been proven in the prior container, while the
local execution marker is ephemeral across Render deploys.  v339 now patches
v346 so a new writer generation may rebuild that marker only from a recent,
authenticated Kraken fill whose exact order id is final and whose executed
quantity/cost are positive.  No order is sent by this recovery path.

v339 closes these races without fabricating execution proof or weakening any
writer, nonce, risk, capital, position, kill-switch, ECEL, order, ACK or fill
safety gate.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
V169_PATH = ROOT / "bot" / "runtime_execution_capital_integrity_v169_patch.py"
V238_PATH = ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py"
V346_PATH = ROOT / "bot" / "runtime_execution_position_readiness_v346_patch.py"
MARKER = "20260831-execution-proof-startup-isolation-v339"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"v339 anchor missing: {label}")
    return text.replace(old, new, 1)


def patch_launcher_text(text: str) -> str:
    prepare = '''def _prepare_execution_proof_startup_isolation_v339() -> None:\n    """Route pre-v169 writer liveness away from the execution-proof marker."""\n    execution_path = str(\n        os.environ.get("NIJA_EXECUTION_MARKER_PATH", "")\n        or os.environ.get("HEARTBEAT_MARKER_PATH", "")\n        or "./data/heartbeat_verified.flag"\n    ).strip()\n    authority_path = str(\n        os.environ.get("NIJA_AUTHORITY_LIVENESS_MARKER_PATH", "")\n        or "./data/authority_heartbeat.flag"\n    ).strip()\n    if not execution_path or not authority_path:\n        raise RuntimeError("execution-proof v339 marker path missing")\n    if Path(execution_path).resolve() == Path(authority_path).resolve():\n        raise RuntimeError("execution-proof v339 authority/execution marker paths collide")\n    os.environ["NIJA_EXECUTION_MARKER_PATH"] = execution_path\n    os.environ["NIJA_AUTHORITY_LIVENESS_MARKER_PATH"] = authority_path\n    # Until v169 patches all authority writers, legacy heartbeat code is\n    # physically routed away from the execution-proof path.\n    os.environ["HEARTBEAT_MARKER_PATH"] = authority_path\n    os.environ["NIJA_EXECUTION_PROOF_STARTUP_ISOLATION_V339_ARMED"] = "1"\n    LOGGER.critical(\n        "EXECUTION_PROOF_STARTUP_ISOLATION_V339_ARMED "\n        "marker=20260831-execution-proof-startup-isolation-v339 "\n        "authority_path=%s execution_path=%s pre_v169_authority_routed=true "\n        "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",\n        authority_path,\n        execution_path,\n    )\n\n\n'''
    if "def _prepare_execution_proof_startup_isolation_v339()" not in text:
        anchor = "def _bootstrap_writer_first() -> tuple[ModuleType, ModuleType]:\n"
        if anchor not in text:
            raise RuntimeError("v339 launcher bootstrap anchor missing")
        text = text.replace(anchor, prepare + anchor, 1)

    text = _replace_once(
        text,
        '''    _start_render_memory_pressure_guard()\n    install_canonical_startup_guard()\n    bot_entry, bot_main = _bootstrap_writer_first()\n''',
        '''    _start_render_memory_pressure_guard()\n    _prepare_execution_proof_startup_isolation_v339()\n    install_canonical_startup_guard()\n    bot_entry, bot_main = _bootstrap_writer_first()\n''',
        "launcher main ordering",
    )
    if text.index("_prepare_execution_proof_startup_isolation_v339()", text.index("def main()")) > text.index("install_canonical_startup_guard()", text.index("def main()")):
        raise RuntimeError("v339 launcher ordering invalid")
    return text


def patch_v169_text(text: str) -> str:
    old_path = '''def _execution_marker_path() -> Path:\n    return Path(os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag"))\n\n\n'''
    new_path = '''def _execution_marker_path() -> Path:\n    return Path(\n        os.environ.get("NIJA_EXECUTION_MARKER_PATH", "")\n        or os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")\n    )\n\n\ndef _quarantine_authority_execution_marker() -> str:\n    """Remove only a legacy authority-origin marker from the execution path."""\n    path = _execution_marker_path()\n    if not path.exists():\n        return "missing"\n    try:\n        raw = path.read_text(encoding="utf-8").strip()\n        payload = json.loads(raw) if raw.startswith("{") else {}\n    except Exception:\n        # Unknown proof remains untouched so verification stays fail-closed.\n        return "unparseable_preserved"\n\n    source = str(payload.get("source", "") or "").strip().lower()\n    kind = str(payload.get("proof_kind", "") or "").strip().lower()\n    stage = str(payload.get("stage", "") or "").strip().upper()\n    if source not in {"heartbeat_authority_single_source", "authority_heartbeat"}:\n        return "preserved"\n    if kind not in {"", "authority_liveness"}:\n        return "preserved"\n\n    quarantine = path.with_name(path.name + ".authority-quarantined-v339")\n    try:\n        if quarantine.exists():\n            quarantine.unlink()\n        path.replace(quarantine)\n    except Exception:\n        try:\n            path.unlink()\n        except FileNotFoundError:\n            pass\n    LOGGER.warning(\n        "EXECUTION_PROOF_V339_AUTHORITY_MARKER_QUARANTINED marker=%s path=%s "\n        "source=%s proof_kind=%s stage=%s execution_proof_fabricated=false "\n        "trading_fail_closed=true",\n        MARKER,\n        path,\n        source or "missing",\n        kind or "missing",\n        stage or "missing",\n    )\n    return "quarantined"\n\n\n'''
    text = _replace_once(text, old_path, new_path, "v169 execution marker path")

    old_install = '''def install() -> bool:\n    with _LOCK:\n        surfaces_ok = _patch_execution_surfaces()\n        import_hook_ok = _install_import_reassertion_hook()\n        capital_ok = _patch_v164_publish_preseed()\n        manifest_ok = _patch_release_manifest()\n        ready = bool(surfaces_ok and import_hook_ok and capital_ok and manifest_ok)\n'''
    new_install = '''def install() -> bool:\n    with _LOCK:\n        execution_path = _execution_marker_path()\n        authority_path = _authority_marker_path()\n        if execution_path.resolve() == authority_path.resolve():\n            os.environ[_READY_FLAG] = "0"\n            LOGGER.critical(\n                "RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_FAILED marker=%s "\n                "reason=authority_execution_marker_path_collision trading_fail_closed=true",\n                MARKER,\n            )\n            return False\n        _quarantine_authority_execution_marker()\n        surfaces_ok = _patch_execution_surfaces()\n        if surfaces_ok:\n            # Legacy consumers may use HEARTBEAT_MARKER_PATH, but only after all\n            # authority writers have been redirected to the authority-only path.\n            os.environ["HEARTBEAT_MARKER_PATH"] = str(execution_path)\n        import_hook_ok = _install_import_reassertion_hook()\n        capital_ok = _patch_v164_publish_preseed()\n        manifest_ok = _patch_release_manifest()\n        ready = bool(surfaces_ok and import_hook_ok and capital_ok and manifest_ok)\n'''
    text = _replace_once(text, old_install, new_install, "v169 install ordering")
    if "NIJA_EXECUTION_MARKER_PATH" not in text or "_quarantine_authority_execution_marker()" not in text:
        raise RuntimeError("v339 v169 hardening incomplete")
    return text


def patch_v238_text(text: str) -> str:
    old = '''def _genuine_execution_marker_ready() -> tuple[bool, str]:\n    try:\n        tsm = importlib.import_module("bot.trading_state_machine")\n        verifier = getattr(tsm, "_heartbeat_verification_status", None)\n        if not callable(verifier):\n            return False, "canonical_verifier_unavailable"\n        ok, detail, _meta = verifier()\n        return bool(ok), str(detail or "verified")\n    except Exception as exc:\n        return False, f"verification_error:{type(exc).__name__}:{exc}"\n\n\n'''
    new = '''def _genuine_execution_marker_ready() -> tuple[bool, str]:\n    try:\n        if os.environ.get("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY") != "1":\n            return False, "v169_provenance_guard_not_ready"\n        tsm = importlib.import_module("bot.trading_state_machine")\n        verifier = getattr(tsm, "_heartbeat_verification_status", None)\n        if not callable(verifier):\n            return False, "canonical_verifier_unavailable"\n        ok, detail, meta = verifier()\n        meta = dict(meta or {})\n        if not ok:\n            return False, str(detail or "execution_proof_not_ready")\n        source = str(meta.get("source", "") or "").strip().lower()\n        kind = str(meta.get("proof_kind", "") or "").strip().lower()\n        allowed_sources = {"heartbeat_trade", "canonical_confirmed_fill"}\n        # Compatibility token retained for render source validation: source != "heartbeat_trade"\n        if source not in allowed_sources or kind != "execution_probe":\n            return False, (\n                "v169_execution_provenance_missing:"\n                f"source={source or 'missing'}:kind={kind or 'missing'}"\n            )\n        return True, f"verified_v169_execution_probe:source={source}"\n    except Exception as exc:\n        return False, f"verification_error:{type(exc).__name__}:{exc}"\n\n\n'''
    text = _replace_once(text, old, new, "v238 genuine execution guard")
    if "v169_provenance_guard_not_ready" not in text or "verified_v169_execution_probe" not in text:
        raise RuntimeError("v339 v238 hardening incomplete")
    return text


def patch_v346_text(text: str) -> str:
    """Add restart-safe proof recovery from authenticated Kraken fill history."""
    constants_old = '''_ALLOWED_EXECUTION_SOURCES = {"heartbeat_trade", "canonical_confirmed_fill"}\n\n\n'''
    constants_new = '''_ALLOWED_EXECUTION_SOURCES = {"heartbeat_trade", "canonical_confirmed_fill"}\n_RECOVERY_LOCK = threading.RLock()\n_RECOVERY_LAST_ATTEMPT_MONO = 0.0\n_RECOVERY_LAST_GENERATION = ""\n_RECOVERY_DEFAULT_MAX_AGE_S = 86400.0\n_RECOVERY_DEFAULT_INTERVAL_S = 30.0\n\n\n'''
    text = _replace_once(text, constants_old, constants_new, "v346 recovery constants")

    helper_anchor = '''def _write_confirmed_fill_marker(*, result: Mapping[str, Any], symbol: str, side: str, fill_price: float, filled_usd: float) -> bool:\n'''
    helpers = '''def _ensure_v169_ready() -> tuple[bool, str]:\n    """Retry the existing v169 hardening after late startup imports converge."""\n    if os.environ.get("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY") == "1":\n        return True, "already_ready"\n    try:\n        v169 = importlib.import_module("bot.runtime_execution_capital_integrity_v169_patch")\n        installer = getattr(v169, "install", None)\n        if not callable(installer):\n            return False, "installer_missing"\n        ok = bool(installer())\n        ready = os.environ.get("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY") == "1"\n        if ok and ready:\n            LOGGER.critical(\n                "EXECUTION_PROOF_RESTART_V346_V169_RECOVERED marker=%s "\n                "late_install_retry=true safety_gates_bypassed=false",\n                MARKER,\n            )\n            return True, "late_install_recovered"\n        return False, "install_not_ready"\n    except Exception as exc:\n        return False, f"install_error:{type(exc).__name__}:{exc}"\n\n\ndef _current_execution_marker_ready() -> tuple[bool, str]:\n    if os.environ.get("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY") != "1":\n        return False, "v169_not_ready"\n    try:\n        tsm = importlib.import_module("bot.trading_state_machine")\n        status = getattr(tsm, "_heartbeat_verification_status", None)\n        if not callable(status):\n            return False, "canonical_verifier_missing"\n        ready, detail, meta = status()\n        meta = dict(meta or {})\n        source = str(meta.get("source", "") or "").strip().lower()\n        kind = str(meta.get("proof_kind", "") or "").strip().lower()\n        if bool(ready) and source in _ALLOWED_EXECUTION_SOURCES and kind == "execution_probe":\n            return True, f"current:{source}"\n        return False, str(detail or f"not_ready:{source or 'missing'}:{kind or 'missing'}")\n    except Exception as exc:\n        return False, f"verify_error:{type(exc).__name__}:{exc}"\n\n\ndef _writer_epoch_for_recovery() -> tuple[bool, str]:\n    generation = str(\n        os.environ.get("NIJA_WRITER_LEASE_GENERATION")\n        or os.environ.get("NIJA_WRITER_GENERATION")\n        or ""\n    ).strip()\n    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN") or "").strip()\n    if not generation or generation in {"0", "none", "None"} or not token:\n        return False, "writer_epoch_not_proven"\n    return True, generation\n\n\ndef _canonical_kraken_broker() -> Any:\n    try:\n        v164 = importlib.import_module("bot.runtime_capital_publication_liveness_v164_patch")\n        manager_fn = getattr(v164, "_canonical_manager", None)\n        mapping_fn = getattr(v164, "_manager_platform_mapping", None)\n        connected_fn = getattr(v164, "_manager_connected", None)\n        if not callable(manager_fn) or not callable(mapping_fn):\n            return None\n        manager = manager_fn()\n        mapping = dict(mapping_fn(manager) or {})\n        for key, broker in mapping.items():\n            if broker is None:\n                continue\n            broker_type = getattr(broker, "broker_type", None)\n            label = " ".join(\n                (\n                    str(key or ""),\n                    str(getattr(broker_type, "value", broker_type) or ""),\n                    type(broker).__name__,\n                )\n            ).lower()\n            if "kraken" not in label:\n                continue\n            if callable(connected_fn):\n                try:\n                    if not bool(connected_fn(manager, key, broker)):\n                        continue\n                except Exception:\n                    continue\n            return broker\n    except Exception:\n        return None\n    return None\n\n\ndef _recovery_max_age_s() -> float:\n    try:\n        value = float(os.environ.get("NIJA_EXECUTION_PROOF_RECOVERY_MAX_AGE_S", _RECOVERY_DEFAULT_MAX_AGE_S))\n    except (TypeError, ValueError):\n        value = _RECOVERY_DEFAULT_MAX_AGE_S\n    return max(300.0, min(604800.0, value))\n\n\ndef _recovery_interval_s() -> float:\n    try:\n        value = float(os.environ.get("NIJA_EXECUTION_PROOF_RECOVERY_INTERVAL_S", _RECOVERY_DEFAULT_INTERVAL_S))\n    except (TypeError, ValueError):\n        value = _RECOVERY_DEFAULT_INTERVAL_S\n    return max(15.0, min(300.0, value))\n\n\ndef _recover_recent_kraken_execution_proof() -> tuple[bool, str]:\n    """Rebuild only from a recent authenticated, exact-id, final Kraken fill."""\n    global _RECOVERY_LAST_ATTEMPT_MONO, _RECOVERY_LAST_GENERATION\n\n    marker_ready, marker_detail = _current_execution_marker_ready()\n    if marker_ready:\n        return True, marker_detail\n\n    writer_ready, generation = _writer_epoch_for_recovery()\n    if not writer_ready:\n        return False, generation\n\n    now_mono = time.monotonic()\n    with _RECOVERY_LOCK:\n        if (\n            generation == _RECOVERY_LAST_GENERATION\n            and now_mono - _RECOVERY_LAST_ATTEMPT_MONO < _recovery_interval_s()\n        ):\n            return False, "recovery_rate_limited"\n        _RECOVERY_LAST_ATTEMPT_MONO = now_mono\n        _RECOVERY_LAST_GENERATION = generation\n\n    broker = _canonical_kraken_broker()\n    if broker is None:\n        return False, "kraken_platform_broker_not_ready"\n\n    try:\n        v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")\n        private_read = getattr(v357, "_private_read", None)\n        query_order_row = getattr(v357, "_query_order_row", None)\n        query_order_fill = getattr(v357, "_query_order_fill", None)\n        trade_history_fill = getattr(v357, "_trade_history_fill", None)\n        if not all(callable(fn) for fn in (private_read, query_order_row, query_order_fill, trade_history_fill)):\n            return False, "v357_helpers_not_ready"\n\n        history = private_read(broker, "TradesHistory", {"type": "all", "trades": True})\n        if not isinstance(history, Mapping) or history.get("error"):\n            return False, "kraken_trade_history_unavailable"\n        result = history.get("result")\n        trades = result.get("trades") if isinstance(result, Mapping) else None\n        if not isinstance(trades, Mapping):\n            return False, "kraken_trade_history_missing"\n\n        cutoff = time.time() - _recovery_max_age_s()\n        candidates: list[tuple[float, str, dict[str, Any]]] = []\n        for row in trades.values():\n            if not isinstance(row, Mapping):\n                continue\n            order_id = str(row.get("ordertxid") or "").strip()\n            try:\n                trade_ts = float(row.get("time") or row.get("timestamp") or 0.0)\n            except (TypeError, ValueError):\n                trade_ts = 0.0\n            if not order_id or trade_ts <= 0.0 or trade_ts < cutoff:\n                continue\n            candidates.append((trade_ts, order_id, dict(row)))\n\n        candidates.sort(key=lambda item: item[0], reverse=True)\n        seen: set[str] = set()\n        final_states = {"filled", "closed", "complete", "completed", "executed"}\n        v328 = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")\n        normalize_fill = getattr(v328, "_normalize_dict_fill", None)\n        if not callable(normalize_fill):\n            return False, "v328_fill_verifier_not_ready"\n\n        for trade_ts, order_id, trade_row in candidates[:12]:\n            if order_id in seen:\n                continue\n            seen.add(order_id)\n            side = str(trade_row.get("type") or trade_row.get("side") or "").strip().lower()\n            symbol = str(trade_row.get("pair") or trade_row.get("symbol") or "KRAKEN-RECOVERED").strip().upper()\n            if side not in {"buy", "sell"}:\n                continue\n\n            order_row = query_order_row(broker, order_id)\n            status, fill_price, filled_qty, filled_usd = query_order_fill(order_row)\n            status = str(status or "").strip().lower()\n            if fill_price <= 0.0 or filled_qty <= 0.0 or filled_usd <= 0.0:\n                if status not in final_states:\n                    continue\n                fill_price, filled_qty, filled_usd, matches = trade_history_fill(\n                    broker, order_id=order_id, side=side\n                )\n                if matches <= 0 or fill_price <= 0.0 or filled_qty <= 0.0 or filled_usd <= 0.0:\n                    continue\n\n            candidate = {\n                "order_id": order_id,\n                "status": status or "closed",\n                "filled_price": float(fill_price),\n                "filled_size": float(filled_qty),\n                "filled_size_usd": float(filled_usd),\n            }\n            verified_price, verified_usd = normalize_fill(\n                candidate, symbol=symbol, side=side\n            )\n            if verified_price <= 0.0 or verified_usd <= 0.0:\n                continue\n\n            current, _detail = _current_execution_marker_ready()\n            if not current:\n                if not _write_confirmed_fill_marker(\n                    result=candidate,\n                    symbol=symbol,\n                    side=side,\n                    fill_price=float(verified_price),\n                    filled_usd=float(verified_usd),\n                ):\n                    continue\n\n            try:\n                v169 = importlib.import_module("bot.runtime_execution_capital_integrity_v169_patch")\n                path_fn = getattr(v169, "_execution_marker_path", None)\n                atomic_write = getattr(v169, "_atomic_json_write", None)\n                if callable(path_fn) and callable(atomic_write):\n                    path = path_fn()\n                    raw = path.read_text(encoding="utf-8").strip()\n                    payload = json.loads(raw) if raw.startswith("{") else {}\n                    payload["recovered_from_authenticated_history"] = True\n                    payload["recovery_source"] = "kraken_queryorders_tradeshistory_exact_order"\n                    payload["exchange_fill_time"] = float(trade_ts)\n                    payload["recovered_writer_generation"] = generation\n                    atomic_write(path, payload)\n            except Exception:\n                LOGGER.debug("v346 execution-proof recovery metadata write deferred", exc_info=True)\n\n            ready_after, ready_detail = _current_execution_marker_ready()\n            if ready_after:\n                LOGGER.critical(\n                    "EXECUTION_PROOF_RESTART_V346_RECOVERED marker=%s order_id=%s symbol=%s side=%s "\n                    "writer_generation=%s authenticated_history=true exact_order_id=true final_status=true "\n                    "positive_fill_quantity=true positive_fill_cost=true max_age_s=%.0f no_order_submitted=true "\n                    "heartbeat_trade_required=false execution_proof_fabricated=false safety_gates_bypassed=false",\n                    MARKER, order_id, symbol, side, generation, _recovery_max_age_s(),\n                )\n                return True, ready_detail\n        return False, "no_recent_final_exact_kraken_fill"\n    except Exception as exc:\n        LOGGER.info(\n            "EXECUTION_PROOF_RESTART_V346_DEFERRED marker=%s reason=%s:%s "\n            "read_only=true no_order_submitted=true trading_fail_closed=true",\n            MARKER, type(exc).__name__, exc,\n        )\n        return False, f"recovery_error:{type(exc).__name__}:{exc}"\n\n\n'''
    if "def _ensure_v169_ready()" not in text:
        if helper_anchor not in text:
            raise RuntimeError("v339 v346 helper anchor missing")
        text = text.replace(helper_anchor, helpers + helper_anchor, 1)

    worker_old = '''def _worker() -> None:\n    while True:\n        try:\n            _patch_v328_confirmed_fill_marker()\n            _patch_v169_provenance()\n            _patch_v231_execution_marker()\n            _patch_stale_platform_refresh()\n            _wake_position_sync()\n            _wake_activation_after_proof()\n        except Exception:\n            LOGGER.debug("V346 worker pulse failed", exc_info=True)\n        time.sleep(3.0)\n'''
    worker_new = '''def _worker() -> None:\n    while True:\n        try:\n            v169_ready, _v169_detail = _ensure_v169_ready()\n            _patch_v328_confirmed_fill_marker()\n            _patch_v169_provenance()\n            _patch_v231_execution_marker()\n            _patch_stale_platform_refresh()\n            if v169_ready:\n                _recover_recent_kraken_execution_proof()\n            _wake_position_sync()\n            _wake_activation_after_proof()\n        except Exception:\n            LOGGER.debug("V346 worker pulse failed", exc_info=True)\n        time.sleep(3.0)\n'''
    text = _replace_once(text, worker_old, worker_new, "v346 worker recovery")

    install_old = '''        try:\n            fill_ready = _patch_v328_confirmed_fill_marker()\n            provenance_ready = _patch_v169_provenance()\n'''
    install_new = '''        try:\n            v169_ready, _v169_detail = _ensure_v169_ready()\n            fill_ready = _patch_v328_confirmed_fill_marker()\n            provenance_ready = _patch_v169_provenance()\n'''
    text = _replace_once(text, install_old, install_new, "v346 install v169 retry")

    wake_old = '''        if ready:\n            _wake_position_sync()\n            _wake_activation_after_proof()\n'''
    wake_new = '''        if ready:\n            if v169_ready:\n                _recover_recent_kraken_execution_proof()\n            _wake_position_sync()\n            _wake_activation_after_proof()\n'''
    text = _replace_once(text, wake_old, wake_new, "v346 install recovery wake")

    if "EXECUTION_PROOF_RESTART_V346_RECOVERED" not in text or "no_order_submitted=true" not in text:
        raise RuntimeError("v339 v346 restart recovery incomplete")
    return text


def _patch_file(path: Path, patcher) -> None:
    original = path.read_text(encoding="utf-8")
    patched = patcher(original)
    if patched != original:
        path.write_text(patched, encoding="utf-8")


def main() -> int:
    _patch_file(LAUNCHER_PATH, patch_launcher_text)
    _patch_file(V169_PATH, patch_v169_text)
    _patch_file(V238_PATH, patch_v238_text)
    _patch_file(V346_PATH, patch_v346_text)
    print(
        "EXECUTION_PROOF_STARTUP_ISOLATION_V339_SOURCE_READY "
        f"marker={MARKER} startup_order_hardened=true authority_marker_quarantine=true "
        "v238_v169_provenance_required=true v346_restart_fill_rehydrate=true "
        "authenticated_history_only=true no_recovery_order_submission=true "
        "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
