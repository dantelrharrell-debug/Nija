"""Production corrective set v18 for NIJA runtime safety.

This patch closes the remaining production gaps observed after nonce/process
writer generation separation:

* distributed writer verification is read-only outside EntrypointWriterAuthority;
* authority heartbeat publication cannot resync writer generation, extend the
  writer lock TTL, or recreate a missing process writer lock;
* live writer authority requires a healthy EntrypointWriterAuthority renewal
  proof and exact process-generation/lock ownership;
* capital hydration never auto-enables the local writer-lock fallback;
* scan-wrapper convergence recognizes the older runtime-convergence scan owner
  and removes the nested same-thread reentrancy trap; and
* EntryPriceStore access from PositionTracker is broker/account scoped, with
  legacy symbol-only records treated as untrusted compatibility data.

No activation, fencing, nonce, kill-switch, capital, strategy, risk, or broker
gate is bypassed. Missing or ambiguous authority fails closed.
"""
from __future__ import annotations

import builtins
import hashlib
import importlib
import json
import logging
import os
import re
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.production_corrective_set_v18")
MARKER = "20260807-production-corrective-set-v18"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_IMPORT_HOOK_FLAG = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_IMPORT_HOOK"
_IMPORTLIB_HOOK_FLAG = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_IMPORTLIB_HOOK"


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _live_mode() -> bool:
    return _truthy("LIVE_CAPITAL_VERIFIED") and not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _writer_lock_key() -> str:
    explicit = str(os.environ.get("NIJA_WRITER_LOCK_KEY", "") or "").strip()
    if explicit:
        return explicit
    scope = str(os.environ.get("NIJA_WRITER_LOCK_SCOPE", "") or "").strip()
    if not scope:
        raw = (
            str(os.environ.get("KRAKEN_PLATFORM_API_KEY", "") or "").strip()
            or str(os.environ.get("KRAKEN_API_KEY", "") or "").strip()
            or "default"
        )
        scope = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"nija:writer_lock:{scope}"


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _process_generation() -> int:
    raw = (
        str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
        or str(os.environ.get("NIJA_WRITER_GENERATION", "") or "").strip()
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _strict_writer_runtime_health() -> tuple[bool, str, Any]:
    module = sys.modules.get("bot.entrypoint_writer_authority") or sys.modules.get("entrypoint_writer_authority")
    if not isinstance(module, ModuleType):
        return False, "entrypoint_writer_module_unavailable", None
    getter = getattr(module, "get_entrypoint_writer_authority", None)
    if not callable(getter):
        return False, "entrypoint_writer_getter_unavailable", None
    try:
        runtime = getter()
    except Exception as exc:
        return False, f"entrypoint_writer_getter_error:{type(exc).__name__}:{exc}", None
    if runtime is None:
        return False, "entrypoint_writer_runtime_missing", None
    if not bool(getattr(runtime, "acquired", False)):
        return False, "entrypoint_writer_not_acquired", runtime
    if bool(getattr(runtime, "lost", False)):
        return False, "entrypoint_writer_lost", runtime
    health = getattr(runtime, "_nija_lease_renewal_health", None)
    if not callable(health):
        return False, "entrypoint_writer_renewal_proof_unavailable", runtime
    try:
        ok, reason, age_s, max_age_s = health()
    except Exception as exc:
        return False, f"entrypoint_writer_renewal_check_error:{type(exc).__name__}:{exc}", runtime
    if not bool(ok):
        return False, f"entrypoint_writer_renewal_unhealthy:{reason}:{age_s:.1f}>{max_age_s:.1f}", runtime
    return True, "renewal_healthy", runtime


def _patch_execution_authority_context(module: ModuleType) -> bool:
    patch_attr = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_EXECUTION_AUTHORITY_PATCHED"
    if getattr(module, patch_attr, False):
        return False
    required = ("get_redis_url", "_connect_redis_for_authority", "_read_current_lease_generation")
    if not all(callable(getattr(module, name, None)) for name in required):
        return False

    def assert_distributed_writer_authority() -> None:
        if _live_mode() and (
            _truthy("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK")
            or _truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
            or _truthy("NIJA_WRITER_FENCING_TOKEN_FALLBACK")
        ):
            raise RuntimeError("STRICT_SINGLE_WRITER_REQUIRED: live distributed-lock bypass refused")

        token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
        generation = _process_generation()
        if not _truthy("NIJA_WRITER_LEASE_ACQUIRED") or not token or generation <= 0:
            raise RuntimeError("STRICT_SINGLE_WRITER_REQUIRED: process writer lease/token/generation incomplete")

        redis_url = str(module.get_redis_url() or "").strip()
        if not redis_url:
            raise RuntimeError("STRICT_SINGLE_WRITER_REQUIRED: Redis URL unavailable")

        client = module._connect_redis_for_authority(redis_url, timeout_s=2)
        lock_key = _writer_lock_key()
        current_text = _as_text(client.get(lock_key))
        if not current_text:
            logger.critical("PROCESS_WRITER_LOCK_MISSING marker=%s lock_key=%s token_prefix=%s action=fail_closed", MARKER, lock_key, token[:8])
            raise RuntimeError(f"STRICT_SINGLE_WRITER_REQUIRED: process writer lock missing lock_key={lock_key}")
        current_token = current_text.split(":", 1)[0]
        if current_token != token:
            logger.critical("PROCESS_WRITER_LOCK_OWNER_MISMATCH marker=%s lock_key=%s expected_prefix=%s current_prefix=%s action=fail_closed", MARKER, lock_key, token[:8], current_token[:8])
            raise RuntimeError("STRICT_SINGLE_WRITER_REQUIRED: process writer lock belongs to another writer")

        redis_generation, generation_err = module._read_current_lease_generation()
        if generation_err or int(redis_generation or 0) != generation:
            raise RuntimeError("STRICT_SINGLE_WRITER_REQUIRED: process writer generation mismatch " f"local={generation} redis={redis_generation} err={generation_err or 'none'}")

        lock = getattr(module, "_FENCE_VERIFY_LOCK", None)
        if lock is not None:
            try:
                with lock:
                    module._FENCE_LAST_CHECK_TS = time.monotonic()
                    module._FENCE_LAST_OK = True
                    module._FENCE_LAST_ERR = ""
            except Exception:
                pass

    module.assert_distributed_writer_authority = assert_distributed_writer_authority
    setattr(module, patch_attr, True)
    os.environ["NIJA_PROCESS_WRITER_VERIFICATION_READ_ONLY"] = "1"
    logger.critical("PROCESS_WRITER_VERIFICATION_READ_ONLY_PATCHED marker=%s module=%s", MARKER, module.__name__)
    return True


def _patch_authority_heartbeat(module: ModuleType) -> bool:
    patch_attr = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_AUTHORITY_HEARTBEAT_PATCHED"
    if getattr(module, patch_attr, False):
        return False
    cls = getattr(module, "AuthorityHeartbeatMonitor", None)
    original_check = getattr(module, "_check_authority_once", None)
    if not isinstance(cls, type) or not callable(original_check):
        return False

    @wraps(original_check)
    def _check_authority_once(timeout_s: float):
        if _truthy("NIJA_WRITER_LEASE_ACQUIRED") and not _truthy("NIJA_WRITER_FENCING_TOKEN_FALLBACK"):
            ok, detail, _runtime = _strict_writer_runtime_health()
            if not ok:
                return False, detail
        return original_check(timeout_s)

    def _write_heartbeat_to_redis(self: Any) -> None:
        try:
            from bot import execution_authority_context as eac
        except ImportError:
            import execution_authority_context as eac  # type: ignore[import]

        token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
        generation = _process_generation()
        lock_key = str(os.environ.get("NIJA_WRITER_LOCK_KEY", "") or "").strip()
        if not _truthy("NIJA_WRITER_LEASE_ACQUIRED") or not token or generation <= 0 or not lock_key:
            raise RuntimeError("authority heartbeat process-writer proof incomplete")

        redis_url = str(eac.get_redis_url() or "").strip()
        if not redis_url:
            raise RuntimeError("authority heartbeat Redis unavailable")
        client = eac._connect_redis_for_authority(redis_url, timeout_s=2)
        self._redis_client = client

        generation_key = str(os.environ.get("NIJA_LEASE_GENERATION_KEY", "") or "").strip() or "nija:lease:generation"
        redis_generation_raw = client.get(generation_key)
        if redis_generation_raw is None:
            raise RuntimeError("authority heartbeat process generation missing in Redis")
        try:
            redis_generation = int(_as_text(redis_generation_raw).strip())
        except ValueError as exc:
            raise RuntimeError("authority heartbeat process generation malformed") from exc
        if redis_generation != generation:
            logger.critical("AUTHORITY_HEARTBEAT_PROCESS_GENERATION_MISMATCH marker=%s local=%s redis=%s action=fail_closed", MARKER, generation, redis_generation)
            raise RuntimeError(f"authority heartbeat process generation mismatch local={generation} redis={redis_generation}")

        current = _as_text(client.get(lock_key))
        if not current:
            logger.critical("AUTHORITY_HEARTBEAT_PROCESS_LOCK_MISSING marker=%s lock_key=%s action=fail_closed", MARKER, lock_key)
            raise RuntimeError("authority heartbeat process writer lock missing")
        current_token = current.split(":", 1)[0]
        if current_token != token:
            logger.critical("AUTHORITY_HEARTBEAT_PROCESS_LOCK_OWNER_MISMATCH marker=%s lock_key=%s expected_prefix=%s current_prefix=%s action=fail_closed", MARKER, lock_key, token[:8], current_token[:8])
            raise RuntimeError("authority heartbeat process writer lock owner mismatch")

        heartbeat_data = {
            "timestamp": time.time(),
            "generation": generation,
            "generation_scope": "process_writer_lock",
            "instance_id": str(os.environ.get("NIJA_WRITER_INSTANCE_ID", "unknown") or "unknown"),
            "token_prefix": token[:8],
            "source": "authority_heartbeat_read_only",
        }
        client.set("nija:writer_heartbeat_active", json.dumps(heartbeat_data, sort_keys=True), ex=30)
        os.environ["NIJA_AUTHORITY_HEARTBEAT_GENERATION_SCOPE_PATCHED"] = "1"
        logger.debug("AUTHORITY_HEARTBEAT_PROCESS_GENERATION_PUBLISHED marker=%s generation=%s lock_key=%s", MARKER, generation, lock_key)

    module._check_authority_once = _check_authority_once
    cls._write_heartbeat_to_redis = _write_heartbeat_to_redis
    setattr(module, patch_attr, True)
    os.environ["NIJA_AUTHORITY_HEARTBEAT_PROCESS_LOCK_READ_ONLY"] = "1"
    logger.critical("AUTHORITY_HEARTBEAT_GENERATION_SCOPE_REPAIR_INSTALLED marker=%s module=%s", MARKER, module.__name__)
    return True


def _patch_capital_authority(module: ModuleType) -> bool:
    patch_attr = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_CAPITAL_AUTHORITY_PATCHED"
    if getattr(module, patch_attr, False):
        return False
    original = getattr(module, "_maybe_auto_enable_live_mode", None)
    if not callable(original):
        return False

    def _maybe_auto_enable_live_mode(real_capital: float, broker_count: int) -> None:
        if float(real_capital or 0.0) <= 0.0 or int(broker_count or 0) < 1:
            return
        if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
            return
        if not _truthy("LIVE_CAPITAL_VERIFIED"):
            os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
            logger.critical("CAPITAL_AUTHORITY_LIVE_CAPITAL_VERIFIED marker=%s real_capital=%.2f broker_count=%d writer_bypass_auto_enable=false", MARKER, float(real_capital or 0.0), int(broker_count or 0))

    module._maybe_auto_enable_live_mode = _maybe_auto_enable_live_mode
    setattr(module, patch_attr, True)
    os.environ["NIJA_CAPITAL_AUTHORITY_WRITER_BYPASS_SEPARATED"] = "1"
    return True


def _scope_token(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_.-]+", "_", str(value or "").strip().lower())
    return cleaned.strip("_") or "unknown"


def _broker_scope(broker: Any) -> str:
    account = ""
    venue = ""
    for attr in ("account_identifier", "account_id", "user_id", "account_name", "owner_id"):
        value = getattr(broker, attr, None)
        if value:
            account = _scope_token(str(value))
            break
    if not account:
        account_type = getattr(broker, "account_type", None)
        account = _scope_token(str(getattr(account_type, "value", account_type) or "platform"))
    text_parts: list[str] = []
    for attr in ("broker_type", "broker_name", "name", "exchange", "exchange_name"):
        try:
            value = getattr(broker, attr, "")
            value = getattr(value, "value", value)
            text_parts.append(str(value or ""))
        except Exception:
            pass
    text = (" ".join(text_parts) + " " + type(broker).__name__).lower()
    for candidate in ("kraken", "coinbase", "okx", "alpaca", "binance"):
        if candidate in text:
            venue = candidate
            break
    return f"{account}:{venue or 'unknown'}"


def _position_tracker_scope(tracker: Any) -> str:
    storage = str(getattr(tracker, "storage_file", "") or "")
    base = os.path.splitext(os.path.basename(storage))[0]
    if base.startswith("positions_"):
        base = base[len("positions_"):]
    if base and base != "positions":
        return _scope_token(base).replace("_", ":", 1) if "_" in base else _scope_token(base)
    broker = getattr(tracker, "broker", None) or getattr(tracker, "_broker", None)
    if broker is not None:
        return _broker_scope(broker)
    return "legacy:unscoped"


class _ScopedStoreView:
    def __init__(self, store: Any, scope: str) -> None:
        self._store = store
        self._scope = scope

    def get(self, symbol: str):
        getter = getattr(self._store, "get_scoped", None)
        return getter(self._scope, symbol) if callable(getter) else None

    def get_price(self, symbol: str):
        record = self.get(symbol)
        return getattr(record, "price", None) if record is not None else None

    def save(self, symbol: str, price: float, source: str = "execution", quantity: float = 0.0) -> None:
        saver = getattr(self._store, "save_scoped", None)
        if callable(saver):
            saver(self._scope, symbol, price, source=source, quantity=quantity)

    def clear(self, symbol: str) -> None:
        clearer = getattr(self._store, "clear_scoped", None)
        if callable(clearer):
            clearer(self._scope, symbol)


def _patch_entry_price_store(module: ModuleType) -> bool:
    patch_attr = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_ENTRY_PRICE_STORE_PATCHED"
    if getattr(module, patch_attr, False):
        return False
    cls = getattr(module, "EntryPriceStore", None)
    record_cls = getattr(module, "EntryPriceRecord", None)
    if not isinstance(cls, type) or not isinstance(record_cls, type):
        return False

    def _key(scope: str, symbol: str) -> str:
        return f"{_scope_token(scope)}::{str(symbol or '').strip()}"

    def save_scoped(self: Any, scope: str, symbol: str, price: float, source: str = "execution", quantity: float = 0.0) -> None:
        key = _key(scope, symbol)
        record = record_cls(price=float(price), timestamp=int(time.time()), source=str(source), quantity=float(quantity))
        with self._lock:
            self._records[key] = record
            self._persist()
        logger.debug("ENTRY_PRICE_SCOPED_SAVE marker=%s scope=%s symbol=%s price=%.8f qty=%.12f source=%s", MARKER, scope, symbol, float(price), float(quantity), source)

    def get_scoped(self: Any, scope: str, symbol: str):
        with self._lock:
            return self._records.get(_key(scope, symbol))

    def get_price_scoped(self: Any, scope: str, symbol: str):
        record = get_scoped(self, scope, symbol)
        return record.price if record is not None else None

    def clear_scoped(self: Any, scope: str, symbol: str) -> None:
        key = _key(scope, symbol)
        with self._lock:
            if key in self._records:
                del self._records[key]
                self._persist()

    def _run_repair(self: Any, broker_getter: Callable, symbols_getter: Callable | None) -> None:
        try:
            broker = broker_getter()
            if broker is None or not callable(getattr(broker, "get_real_entry_price", None)):
                return
            scope = _broker_scope(broker)
            if symbols_getter:
                symbols = [str(s) for s in list(symbols_getter())]
            else:
                prefix = f"{_scope_token(scope)}::"
                with self._lock:
                    scoped_keys = [str(k) for k in self._records.keys() if str(k).startswith(prefix)]
                symbols = [k.split("::", 1)[1] for k in scoped_keys]
            repaired = 0
            for symbol in symbols:
                existing = get_scoped(self, scope, symbol)
                if existing is not None and str(existing.source) == "execution":
                    continue
                try:
                    api_price = broker.get_real_entry_price(symbol)
                except Exception as exc:
                    logger.debug("ENTRY_PRICE_SCOPED_REPAIR_LOOKUP_FAILED scope=%s symbol=%s err=%s", scope, symbol, exc)
                    continue
                if api_price and float(api_price) > 0:
                    qty = float(getattr(existing, "quantity", 0.0) or 0.0) if existing is not None else 0.0
                    save_scoped(self, scope, symbol, float(api_price), source="api", quantity=qty)
                    repaired += 1
                    logger.info("ENTRY_PRICE_SCOPED_REPAIR marker=%s scope=%s symbol=%s price=%.8f qty=%.12f", MARKER, scope, symbol, float(api_price), qty)
            if repaired:
                logger.info("ENTRY_PRICE_SCOPED_REPAIR_SWEEP marker=%s scope=%s repaired=%d", MARKER, scope, repaired)
        except Exception as exc:
            logger.warning("ENTRY_PRICE_SCOPED_REPAIR_FAILED marker=%s err=%s", MARKER, exc)

    cls.save_scoped = save_scoped
    cls.get_scoped = get_scoped
    cls.get_price_scoped = get_price_scoped
    cls.clear_scoped = clear_scoped
    cls._run_repair = _run_repair
    setattr(module, patch_attr, True)
    os.environ["NIJA_ENTRY_PRICE_STORE_BROKER_SCOPED"] = "1"
    logger.critical("ENTRY_PRICE_STORE_BROKER_SCOPE_PATCHED marker=%s", MARKER)
    return True


def _patch_position_tracker(module: ModuleType) -> bool:
    patch_attr = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_POSITION_TRACKER_PATCHED"
    if getattr(module, patch_attr, False):
        return False
    cls = getattr(module, "PositionTracker", None)
    if not isinstance(cls, type):
        return False
    original_init = getattr(cls, "__init__", None)
    original_track_exit = getattr(cls, "track_exit", None)
    if not callable(original_init) or not callable(original_track_exit):
        return False

    @wraps(original_init)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        store = getattr(self, "_eps", None)
        if store is not None:
            scope = _position_tracker_scope(self)
            self._nija_entry_price_scope = scope
            self._nija_entry_price_store_raw = store
            self._eps = _ScopedStoreView(store, scope)

    def _persist_entry_price(self: Any, symbol: str, price: float, quantity: float, source: str) -> None:
        if price <= 0 or not bool(self._source_verified(source, price)):
            return
        store = getattr(self, "_eps", None)
        if store is None:
            return
        try:
            store.save(symbol, price, source=source, quantity=quantity)
        except Exception as exc:
            logger.debug("POSITION_TRACKER_SCOPED_ENTRY_SAVE_FAILED symbol=%s err=%s", symbol, exc)

    @wraps(original_track_exit)
    def track_exit(self: Any, symbol: str, exit_quantity: float = None) -> bool:
        success = bool(original_track_exit(self, symbol, exit_quantity))
        if not success:
            return False
        remaining = None
        try:
            remaining = self.positions.get(symbol)
        except Exception:
            pass
        if remaining is None:
            store = getattr(self, "_eps", None)
            if store is not None:
                try:
                    store.clear(symbol)
                except Exception:
                    pass
        return True

    cls.__init__ = __init__
    cls._persist_entry_price = _persist_entry_price
    cls.track_exit = track_exit
    setattr(module, patch_attr, True)
    logger.critical("POSITION_TRACKER_ENTRY_PRICE_SCOPE_PATCHED marker=%s", MARKER)
    return True


def _patch_scan_wrapper(module: ModuleType) -> bool:
    patch_attr = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_SCAN_WRAPPER_PATCHED"
    if getattr(module, patch_attr, False):
        return False
    markers = tuple(getattr(module, "_KNOWN_WRAPPER_MARKERS", ()) or ())
    if "_nija_scan_identity_lock_v2" not in markers:
        module._KNOWN_WRAPPER_MARKERS = markers + ("_nija_scan_identity_lock_v2",)
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        core = sys.modules.get(name)
        cls = getattr(core, "NijaCoreLoop", None) if isinstance(core, ModuleType) else None
        current = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
        if not callable(current):
            continue
        if getattr(current, "_nija_scan_wrapper_release", "") == getattr(module, "_MARKER", ""):
            base = getattr(current, "__wrapped__", None)
            unwrap = getattr(module, "_unwrap_known", None)
            patch_core = getattr(module, "_patch_core_loop", None)
            if callable(base) and callable(unwrap) and callable(patch_core):
                resolved, depth, cycle = unwrap(base)
                if callable(resolved) and resolved is not base and not cycle:
                    setattr(cls, "run_scan_phase", base)
                    patch_core(core)
                    logger.critical("SCAN_NESTED_OWNER_REMOVED marker=%s module=%s removed_layers=%d", MARKER, name, depth)
    setattr(module, patch_attr, True)
    os.environ["NIJA_SCAN_IDENTITY_OWNER_COLLAPSED"] = "1"
    return True


def _patch_runtime_convergence_v2(module: ModuleType) -> bool:
    patch_attr = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_RUNTIME_SCAN_OWNER_GUARDED"
    if getattr(module, patch_attr, False):
        return False
    original = getattr(module, "_patch_core_loop", None)
    if not callable(original):
        return False

    @wraps(original)
    def _patch_core_loop(core_module: ModuleType) -> bool:
        cls = getattr(core_module, "NijaCoreLoop", None)
        current = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
        scan_module = sys.modules.get("scan_wrapper_convergence_repair_patch") or sys.modules.get("bot.scan_wrapper_convergence_repair_patch")
        chain_has = getattr(scan_module, "_chain_has_current_owner", None) if isinstance(scan_module, ModuleType) else None
        if callable(current) and callable(chain_has) and bool(chain_has(current)):
            logger.debug("RUNTIME_V2_SCAN_OWNER_DELEGATED marker=%s", MARKER)
            return True
        return bool(original(core_module))

    module._patch_core_loop = _patch_core_loop
    setattr(module, patch_attr, True)
    return True


def _capital_fallback_status() -> dict[str, Any]:
    for name in ("nija_capital_refresh_stall_guard_v35_prebot", "capital_refresh_stall_guard_v35", "bot.capital_refresh_stall_guard_v35"):
        mod = sys.modules.get(name)
        getter = getattr(mod, "current_refresh_fallback_status", None) if isinstance(mod, ModuleType) else None
        if callable(getter):
            try:
                return dict(getter() or {})
            except Exception:
                return {}
    return {}


def _patch_capital_flow(module: ModuleType) -> bool:
    patch_attr = "_NIJA_PRODUCTION_CORRECTIVE_SET_V18_CAPITAL_FLOW_PATCHED"
    if getattr(module, patch_attr, False):
        return False
    confidence_cls = getattr(module, "CapitalConfidence", None)
    trace = getattr(module, "_log_snapshot_trace_throttled", None)
    if not isinstance(confidence_cls, type) or not callable(trace):
        return False
    original_compute = confidence_cls.compute

    def compute(kraken_response_age_s: float, assets_priced_success_pct: float, api_error_count: int, freshness_ttl_s: float = getattr(module, "FRESHNESS_TTL_S", 90.0)):
        result = original_compute(kraken_response_age_s, assets_priced_success_pct, api_error_count, freshness_ttl_s)
        status = _capital_fallback_status()
        if not bool(status.get("used_fallback")):
            return result
        all_recent = bool(status.get("all_recent"))
        excluded = bool(status.get("excluded_brokers"))
        freshness = 0.0 if (not all_recent or excluded) else min(float(result.freshness_score), 0.50)
        pricing = float(result.pricing_score)
        errors = min(float(result.error_score), 0.50 if excluded else 0.75)
        score = round(0.50 * freshness + 0.35 * pricing + 0.15 * errors, 6)
        high = float(getattr(module, "CONFIDENCE_HIGH_THRESHOLD", 0.80))
        medium = float(getattr(module, "CONFIDENCE_MEDIUM_THRESHOLD", 0.40))
        band_enum = getattr(module, "CapitalConfidenceBand")
        band = band_enum.HIGH if score >= high else band_enum.MEDIUM if score >= medium else band_enum.LOW
        return confidence_cls(freshness_score=freshness, pricing_score=pricing, error_score=errors, confidence_score=score, band=band)

    @wraps(trace)
    def _log_snapshot_trace_throttled(balances: dict[str, float], valid_brokers: int, source: str) -> None:
        status = _capital_fallback_status()
        if bool(status.get("used_fallback")):
            source = "cached_live_observation" if bool(status.get("all_recent")) else "partial_or_excluded_fallback"
        return trace(balances, valid_brokers, source)

    confidence_cls.compute = staticmethod(compute)
    module._log_snapshot_trace_throttled = _log_snapshot_trace_throttled
    setattr(module, patch_attr, True)
    os.environ["NIJA_CAPITAL_FALLBACK_PROVENANCE_PATCHED"] = "1"
    return True


def _patch_loaded() -> bool:
    changed = False
    targets: tuple[tuple[tuple[str, ...], Callable[[ModuleType], bool]], ...] = (
        (("bot.execution_authority_context", "execution_authority_context"), _patch_execution_authority_context),
        (("bot.authority_heartbeat", "authority_heartbeat"), _patch_authority_heartbeat),
        (("bot.capital_authority", "capital_authority"), _patch_capital_authority),
        (("bot.entry_price_store", "entry_price_store"), _patch_entry_price_store),
        (("bot.position_tracker", "position_tracker"), _patch_position_tracker),
        (("scan_wrapper_convergence_repair_patch", "bot.scan_wrapper_convergence_repair_patch"), _patch_scan_wrapper),
        (("runtime_convergence_v2_patch", "bot.runtime_convergence_v2_patch"), _patch_runtime_convergence_v2),
        (("bot.capital_flow_state_machine", "capital_flow_state_machine"), _patch_capital_flow),
    )
    for names, patcher in targets:
        seen: set[int] = set()
        for name in names:
            module = sys.modules.get(name)
            if isinstance(module, ModuleType) and id(module) not in seen:
                seen.add(id(module))
                try:
                    changed = bool(patcher(module)) or changed
                except Exception:
                    logger.exception("PRODUCTION_CORRECTIVE_SET_PATCH_FAILED marker=%s module=%s", MARKER, name)
    return changed


def _interesting_import(name: str) -> bool:
    suffixes = ("execution_authority_context", "authority_heartbeat", "capital_authority", "entry_price_store", "position_tracker", "scan_wrapper_convergence_repair_patch", "runtime_convergence_v2_patch", "capital_flow_state_machine")
    return any(str(name or "").endswith(suffix) for suffix in suffixes)


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _IMPORT_HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                module = original_import(name, globals, locals, fromlist, level)
                if _interesting_import(name):
                    _patch_loaded()
                return module

            builtins.__import__ = importing
            setattr(builtins, _IMPORT_HOOK_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_HOOK_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                module = original_import_module(name, package)
                if _interesting_import(name):
                    _patch_loaded()
                return module

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_HOOK_FLAG, True)

        _INSTALLED = True
        os.environ["NIJA_PRODUCTION_CORRECTIVE_SET_V18_INSTALLED"] = "1"
        os.environ["NIJA_PRODUCTION_CORRECTIVE_SET_V18_MARKER"] = MARKER
        logger.critical("PRODUCTION_CORRECTIVE_SET_V18_INSTALLED marker=%s fail_closed=true writer_lock_read_only_outside_owner=true entry_price_scoped=true", MARKER)
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_loaded",
    "_patch_execution_authority_context",
    "_patch_authority_heartbeat",
    "_patch_capital_authority",
    "_patch_entry_price_store",
    "_patch_position_tracker",
    "_patch_scan_wrapper",
    "_patch_runtime_convergence_v2",
    "_patch_capital_flow",
]
