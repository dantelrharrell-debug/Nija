from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from copy import deepcopy
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.forced_fallback_payload_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_WRAP_ATTR = "_nija_forced_fallback_payload_repair_wrapped_v20260703u"

_FALLBACK_HARD_MAX_SL_PCT = 0.0028
_FALLBACK_DEFAULT_SL_PCT = 0.0025
_FALLBACK_MIN_SL_PCT = 0.0015
_ILLQUID_POLICY_TEXT = "competitive profitability policy blocked illiquid fallback entry"
_MIN_EXPECTANCY_MARGIN = 0.0001
_CACHE_TTL_S = 5.0
_PAYLOAD_CACHE: dict[tuple[int, int, int, str, str], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _wrapper_chain_has_attr(fn: Any, attr: str) -> bool:
    seen: set[int] = set()
    cur = fn
    while callable(cur) and id(cur) not in seen:
        seen.add(id(cur))
        if getattr(cur, attr, False):
            return True
        cur = getattr(cur, "__wrapped__", None)
    return False


def _coerce_probability(value: Any) -> float:
    try:
        p = float(value)
    except Exception:
        return 0.0
    if p > 1.0:
        p = p / 100.0
    return max(0.0, min(p, 1.0))


def _coerce_price(value: Any) -> float:
    if isinstance(value, dict):
        for key in ("tp1", "target", "price", "take_profit", "value", "level"):
            try:
                p = float(value.get(key) or 0.0)
                if p > 0.0:
                    return p
            except Exception:
                pass
        return 0.0
    if isinstance(value, (list, tuple)):
        for item in value:
            p = _coerce_price(item)
            if p > 0.0:
                return p
        return 0.0
    try:
        p = float(value or 0.0)
        return p if p > 0.0 else 0.0
    except Exception:
        return 0.0


def _symbol_from_sig(sig: Any) -> str:
    return str(getattr(sig, "symbol", "UNKNOWN") or "UNKNOWN")


def _hold_skip(symbol: str, *, reason: str, stage: str, detail: str = "") -> dict[str, Any]:
    return {
        "action": "hold",
        "reason": reason,
        "filter_stage": stage,
        "detail": detail,
        "symbol": symbol,
        "blocked_before_execute_action": True,
        "skip_before_execute_action": True,
        "fallback_entry_skipped": True,
        "forced_fallback": False,
        "fallback_entry": False,
        "order_should_not_submit": True,
    }


def _signal_expected_win_rate(sig: Any) -> float:
    for name in (
        "expected_win_rate",
        "win_rate",
        "win_probability",
        "probability_of_success",
        "success_probability",
        "edge_probability",
    ):
        p = _coerce_probability(getattr(sig, name, None))
        if p > 0.0:
            return p
    try:
        metadata = getattr(sig, "metadata", None)
        if isinstance(metadata, dict):
            for name in (
                "expected_win_rate",
                "win_rate",
                "win_probability",
                "probability_of_success",
                "success_probability",
                "edge_probability",
            ):
                p = _coerce_probability(metadata.get(name))
                if p > 0.0:
                    return p
    except Exception:
        pass
    try:
        analysis = getattr(sig, "analysis", None)
        if isinstance(analysis, dict):
            for name in (
                "expected_win_rate",
                "win_rate",
                "win_probability",
                "probability_of_success",
                "success_probability",
                "edge_probability",
            ):
                p = _coerce_probability(analysis.get(name))
                if p > 0.0:
                    return p
    except Exception:
        pass
    return 0.0


def _estimate_expected_win_rate(sig: Any, payload: dict[str, Any]) -> tuple[float, str]:
    explicit = _signal_expected_win_rate(sig)
    if explicit > 0.0:
        return explicit, "explicit_signal"

    for source_name, source in (("payload", payload), ("take_profit", payload.get("take_profit"))):
        if isinstance(source, dict):
            for key in ("expected_win_rate", "win_rate", "win_probability", "probability", "probability_of_success"):
                p = _coerce_probability(source.get(key))
                if p > 0.0:
                    return p, source_name

    score = 0.0
    for name in ("composite_score", "entry_score", "score", "confidence"):
        try:
            score = float(getattr(sig, name, 0.0) or 0.0)
            if score > 0.0:
                break
        except Exception:
            continue
    if score <= 0.0 and isinstance(payload, dict):
        for name in ("composite_score", "entry_score", "score", "confidence"):
            try:
                score = float(payload.get(name) or 0.0)
                if score > 0.0:
                    break
            except Exception:
                continue
    if score <= 0.0:
        return 0.0, "missing"

    score_norm = score / 100.0 if score > 1.0 else score
    score_norm = max(0.0, min(score_norm, 1.0))
    floor = _float_env("NIJA_FALLBACK_ESTIMATED_WIN_RATE_FLOOR", 0.52)
    cap = _float_env("NIJA_FALLBACK_ESTIMATED_WIN_RATE_CAP", 0.68)
    estimate = max(floor, min(cap, 0.45 + (0.30 * score_norm)))
    return _coerce_probability(estimate), "estimated_from_signal_score"


def _propagate_expected_win_rate(payload: dict[str, Any], sig: Any) -> tuple[dict[str, Any], float, str]:
    expected_wr, source = _estimate_expected_win_rate(sig, payload)
    if expected_wr <= 0.0:
        return payload, 0.0, source

    payload["expected_win_rate"] = expected_wr
    payload["expected_win_rate_source"] = source
    tp = payload.get("take_profit")
    if isinstance(tp, dict):
        tp["expected_win_rate"] = expected_wr
        tp["expected_win_rate_source"] = source
    elif isinstance(tp, list):
        for item in tp:
            if isinstance(item, dict):
                item["expected_win_rate"] = expected_wr
                item["expected_win_rate_source"] = source
    return payload, expected_wr, source


def _fallback_sl_pct() -> float:
    requested = _float_env("NIJA_FALLBACK_REPAIR_SL_PCT", _FALLBACK_DEFAULT_SL_PCT)
    return max(_FALLBACK_MIN_SL_PCT, min(requested, _FALLBACK_HARD_MAX_SL_PCT))


def _as_tp_dict(tp: Any) -> dict[str, float]:
    if isinstance(tp, dict):
        out: dict[str, float] = {}
        for key in ("tp1", "target", "price", "take_profit", "level"):
            price = _coerce_price(tp.get(key))
            if price > 0.0:
                out["tp1"] = price
                break
        for key in ("tp2", "target2"):
            price = _coerce_price(tp.get(key))
            if price > 0.0:
                out["tp2"] = price
                break
        for key in ("tp3", "target3"):
            price = _coerce_price(tp.get(key))
            if price > 0.0:
                out["tp3"] = price
                break
        levels = tp.get("levels")
        if isinstance(levels, (list, tuple)):
            prices = [_coerce_price(item) for item in levels]
            prices = [p for p in prices if p > 0.0]
            if prices and "tp1" not in out:
                out["tp1"] = prices[0]
            if len(prices) > 1 and "tp2" not in out:
                out["tp2"] = prices[1]
            if len(prices) > 2 and "tp3" not in out:
                out["tp3"] = prices[2]
        for key, value in tp.items():
            if key not in out and key not in {"levels"}:
                try:
                    if isinstance(value, (str, int, float)):
                        out[key] = value  # type: ignore[assignment]
                except Exception:
                    pass
        return out
    if isinstance(tp, (list, tuple)):
        prices = [_coerce_price(item) for item in tp]
        prices = [p for p in prices if p > 0.0]
        out = {}
        if len(prices) > 0:
            out["tp1"] = prices[0]
        if len(prices) > 1:
            out["tp2"] = prices[1]
        if len(prices) > 2:
            out["tp3"] = prices[2]
        return out
    price = _coerce_price(tp)
    return {"tp1": price} if price > 0.0 else {}


def _tp_pct(entry: float, target: float, action: str) -> float:
    if entry <= 0.0 or target <= 0.0:
        return 0.0
    if action == "enter_short":
        return max(0.0, (entry - target) / entry)
    return max(0.0, (target - entry) / entry)


def _price_for_pct(entry: float, pct: float, action: str) -> float:
    return entry * (1.0 - pct) if action == "enter_short" else entry * (1.0 + pct)


def _normalize_take_profit_geometry(payload: Any) -> tuple[Any, bool, str]:
    if not isinstance(payload, dict):
        return payload, False, "non_dict"
    if not bool(payload.get("fallback_entry") or payload.get("forced_fallback")):
        return payload, False, "not_fallback"
    try:
        entry = float(payload.get("entry_price") or 0.0)
    except Exception:
        return payload, False, "missing_entry_price"
    if entry <= 0.0:
        return payload, False, "missing_entry_price"

    action = str(payload.get("action") or "enter_long").strip().lower()
    if action not in {"enter_long", "enter_short"}:
        return payload, False, "invalid_action"

    tp = _as_tp_dict(payload.get("take_profit"))
    if not tp.get("tp1"):
        return payload, False, "missing_take_profit"

    min_tp1 = max(0.0100, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP1_PCT", 0.0120))
    min_tp2 = max(min_tp1 + 0.003, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP2_PCT", 0.0180))
    min_tp3 = max(min_tp2 + 0.004, _float_env("NIJA_FALLBACK_REPAIR_MIN_TP3_PCT", 0.0260))

    old_tp1 = _tp_pct(entry, float(tp.get("tp1") or 0.0), action)
    old_tp2 = _tp_pct(entry, float(tp.get("tp2") or 0.0), action)
    old_tp3 = _tp_pct(entry, float(tp.get("tp3") or 0.0), action)
    new_tp1 = max(old_tp1, min_tp1)
    new_tp2 = max(old_tp2, min_tp2, new_tp1 + 0.003)
    new_tp3 = max(old_tp3, min_tp3, new_tp2 + 0.004)

    changed = False
    if old_tp1 <= 0.0 or old_tp1 < min_tp1:
        tp["tp1"] = _price_for_pct(entry, new_tp1, action)
        changed = True
    if old_tp2 <= 0.0 or old_tp2 < new_tp2:
        tp["tp2"] = _price_for_pct(entry, new_tp2, action)
        changed = True
    if old_tp3 <= 0.0 or old_tp3 < new_tp3:
        tp["tp3"] = _price_for_pct(entry, new_tp3, action)
        changed = True

    tp["fallback_tp1_pct"] = new_tp1
    tp["fallback_tp2_pct"] = new_tp2
    tp["fallback_tp3_pct"] = new_tp3
    tp["fallback_tp_min_pct"] = min_tp1
    payload["take_profit"] = tp
    if changed:
        payload["fallback_take_profit_geometry_repaired"] = True
        payload["fallback_target_geometry_capped"] = True
        payload["reason"] = str(payload.get("reason") or "fallback_entry") + " [fallback_take_profit_geometry_repaired]"
    return payload, changed, "ok"


def _payload_ev(payload: Any) -> tuple[bool, str, float, float, float]:
    if not isinstance(payload, dict):
        return True, "non_dict_payload", 0.0, 0.0, 0.0
    if not bool(payload.get("fallback_entry") or payload.get("forced_fallback")):
        return True, "not_fallback", 0.0, 0.0, 0.0
    try:
        action = str(payload.get("action") or "").strip().lower()
        entry = float(payload.get("entry_price") or 0.0)
        size = float(payload.get("position_size") or payload.get("usd_size") or payload.get("notional") or 0.0)
        stop = float(payload.get("stop_loss") or 0.0)
        take_profit = payload.get("take_profit")
        tp1 = _coerce_price((take_profit or {}).get("tp1") if isinstance(take_profit, dict) else take_profit)
        expected_wr = _coerce_probability(payload.get("expected_win_rate"))
        if expected_wr <= 0.0 and isinstance(take_profit, dict):
            expected_wr = _coerce_probability(take_profit.get("expected_win_rate"))
    except Exception as exc:
        return False, f"fallback_ev_unavailable:{exc}", 0.0, 0.0, 0.0

    if action not in {"enter_long", "enter_short"}:
        return False, f"fallback_ev_invalid_action:{action}", expected_wr, 0.0, 0.0
    if entry <= 0.0 or size <= 0.0 or stop <= 0.0 or tp1 <= 0.0:
        return False, "fallback_ev_missing_real_price_size_or_geometry", expected_wr, 0.0, 0.0
    if action == "enter_long" and not (stop < entry < tp1):
        return False, f"fallback_ev_invalid_directional_geometry action={action} stop={stop:.8f} entry={entry:.8f} tp1={tp1:.8f}", expected_wr, 0.0, 0.0
    if action == "enter_short" and not (tp1 < entry < stop):
        return False, f"fallback_ev_invalid_directional_geometry action={action} tp1={tp1:.8f} entry={entry:.8f} stop={stop:.8f}", expected_wr, 0.0, 0.0

    win_pct = abs(tp1 - entry) / entry
    loss_pct = abs(entry - stop) / entry
    fee_pct = _float_env("NIJA_FALLBACK_PREFLIGHT_ROUND_TRIP_FEE_PCT", 0.003)
    net_win = max(0.0, win_pct - fee_pct)
    net_loss = loss_pct + fee_pct
    if net_win <= 0.0:
        return False, f"fallback_net_win_nonpositive win_pct={win_pct:.4f} fee_pct={fee_pct:.4f}", expected_wr, 1.0, -net_loss
    breakeven = net_loss / (net_win + net_loss)
    expectancy_pct = (expected_wr * net_win) - ((1.0 - expected_wr) * net_loss)
    ok = expected_wr > 0.0 and expectancy_pct > _MIN_EXPECTANCY_MARGIN and expected_wr > breakeven
    detail = (
        f"expected_wr={expected_wr:.4f} breakeven_wr={breakeven:.4f} "
        f"expectancy_pct={expectancy_pct:.4f} win_pct={win_pct:.4f} loss_pct={loss_pct:.4f} "
        f"fee_pct={fee_pct:.4f} size={size:.4f}"
    )
    return ok, detail, expected_wr, breakeven, expectancy_pct


_STRICT_SCORE_FLOOR = float(os.environ.get("NIJA_FALLBACK_STRICT_SCORE_FLOOR", "60.0"))


def _enforce_fallback_positive_ev(payload: Any, *, sig: Any, symbol: str) -> Any:
    if not isinstance(payload, dict):
        return payload

    # ── Strict geometry pre-check ─────────────────────────────────────────
    # Only allow positive-EV pass-through when ALL real geometry conditions
    # are satisfied.  Missing or zero values mean the payload is not ready
    # for execution and must be blocked before any submit log is emitted.
    try:
        _entry = float(payload.get("entry_price") or 0.0)
        _size  = float(
            payload.get("position_size")
            or payload.get("usd_size")
            or payload.get("notional")
            or 0.0
        )
        _stop  = float(payload.get("stop_loss") or 0.0)
        _tp_raw = payload.get("take_profit")
        _tp1   = _coerce_price(
            (_tp_raw or {}).get("tp1") if isinstance(_tp_raw, dict) else _tp_raw
        )
        _action = str(payload.get("action") or "enter_long").strip().lower()
        # Score from sig (AIEngineSignal.composite_score) or payload fallback
        _score = 0.0
        for _sname in ("composite_score", "entry_score", "score", "confidence"):
            try:
                _score = float(getattr(sig, _sname, 0.0) or 0.0)
                if _score > 0.0:
                    break
            except Exception:
                continue
        if _score <= 0.0:
            for _sname in ("composite_score", "entry_score", "score", "confidence"):
                try:
                    _score = float(payload.get(_sname) or 0.0)
                    if _score > 0.0:
                        break
                except Exception:
                    continue
    except Exception as _geo_exc:
        _geo_fail_detail = f"geometry_read_error:{_geo_exc}"
        logger.warning(
            "FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703u symbol=%s detail=%s action=hold_skip_before_execute",
            symbol,
            _geo_fail_detail,
        )
        return _hold_skip(
            symbol,
            reason="fallback_positive_ev_prefilter_blocked",
            stage="fallback_positive_ev_prefilter",
            detail=_geo_fail_detail,
        )

    _strict_floor = float(os.environ.get("NIJA_FALLBACK_STRICT_SCORE_FLOOR", "60.0"))
    _geo_ok = True
    _geo_fail_reason = ""

    if _entry <= 0.0:
        _geo_ok = False
        _geo_fail_reason = f"entry_price_zero_or_missing entry={_entry}"
    elif _size <= 0.0:
        _geo_ok = False
        _geo_fail_reason = f"position_size_zero_or_missing size={_size}"
    elif _stop <= 0.0:
        _geo_ok = False
        _geo_fail_reason = f"stop_loss_zero_or_missing stop={_stop}"
    elif _tp1 <= 0.0:
        _geo_ok = False
        _geo_fail_reason = f"take_profit_zero_or_missing tp1={_tp1}"
    elif _action == "enter_long" and not (_tp1 > _entry):
        _geo_ok = False
        _geo_fail_reason = f"tp_not_above_entry_for_long entry={_entry:.8f} tp1={_tp1:.8f}"
    elif _action == "enter_short" and not (_tp1 < _entry):
        _geo_ok = False
        _geo_fail_reason = f"tp_not_below_entry_for_short entry={_entry:.8f} tp1={_tp1:.8f}"
    elif _action == "enter_long" and not (_stop < _entry):
        _geo_ok = False
        _geo_fail_reason = f"sl_not_below_entry_for_long entry={_entry:.8f} stop={_stop:.8f}"
    elif _action == "enter_short" and not (_stop > _entry):
        _geo_ok = False
        _geo_fail_reason = f"sl_not_above_entry_for_short entry={_entry:.8f} stop={_stop:.8f}"
    elif _score < _strict_floor:
        _geo_ok = False
        _geo_fail_reason = f"score_below_strict_floor score={_score:.1f} floor={_strict_floor:.1f}"

    if not _geo_ok:
        logger.warning(
            "FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703u symbol=%s detail=%s action=hold_skip_before_execute",
            symbol,
            _geo_fail_reason,
        )
        print(
            f"[NIJA-PRINT] FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703u symbol={symbol} "
            f"detail={_geo_fail_reason}",
            flush=True,
        )
        return _hold_skip(
            symbol,
            reason="fallback_positive_ev_prefilter_blocked",
            stage="fallback_positive_ev_prefilter",
            detail=_geo_fail_reason,
        )

    # ── Geometry is valid — normalise TP and propagate win rate ───────────
    payload, tp_changed, tp_reason = _normalize_take_profit_geometry(payload)
    if tp_changed:
        logger.critical("FORCED_FALLBACK_TP_GEOMETRY_NORMALIZED marker=20260703u symbol=%s reason=%s", symbol, tp_reason)
    if isinstance(payload, dict):
        payload, expected_wr, wr_source = _propagate_expected_win_rate(payload, sig)
        if expected_wr > 0.0:
            logger.info(
                "FORCED_FALLBACK_EXPECTED_WIN_RATE_SET marker=20260703u symbol=%s expected_wr=%.4f source=%s",
                symbol,
                expected_wr,
                wr_source,
            )
    ok, detail, expected_wr, breakeven, expectancy_pct = _payload_ev(payload)
    if ok:
        logger.critical(
            "FORCED_FALLBACK_POSITIVE_EV_ACCEPTED marker=20260703u symbol=%s expected_wr=%.4f breakeven_wr=%.4f expectancy_pct=%.4f score=%.1f",
            symbol,
            expected_wr,
            breakeven,
            expectancy_pct,
            _score,
        )
        print(
            f"[NIJA-PRINT] FORCED_FALLBACK_POSITIVE_EV_ACCEPTED marker=20260703u symbol={symbol} "
            f"expected_wr={expected_wr:.4f} breakeven_wr={breakeven:.4f} expectancy_pct={expectancy_pct:.4f} score={_score:.1f}",
            flush=True,
        )
        return payload
    logger.warning(
        "FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703u symbol=%s detail=%s action=hold_skip_before_execute",
        symbol,
        detail,
    )
    print(
        f"[NIJA-PRINT] FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703u symbol={symbol} "
        f"expected_wr={expected_wr:.4f} breakeven_wr={breakeven:.4f} expectancy_pct={expectancy_pct:.4f}",
        flush=True,
    )
    return _hold_skip(symbol, reason="fallback_positive_ev_prefilter_blocked", stage="fallback_positive_ev_prefilter", detail=detail)


def _cap_payload_geometry(payload: Any) -> tuple[Any, bool, float, float]:
    if not isinstance(payload, dict):
        return payload, False, 0.0, 0.0
    try:
        price = float(payload.get("entry_price") or 0.0)
        stop = float(payload.get("stop_loss") or 0.0)
    except Exception:
        return payload, False, 0.0, 0.0
    if price <= 0.0 or stop <= 0.0:
        return payload, False, 0.0, 0.0
    old_sl_pct = abs((price - stop) / price)
    capped_pct = _fallback_sl_pct()
    if old_sl_pct <= capped_pct:
        return payload, False, old_sl_pct, old_sl_pct
    action = str(payload.get("action") or "enter_long").lower()
    payload["stop_loss"] = price * (1.0 + capped_pct) if action == "enter_short" else price * (1.0 - capped_pct)
    tp = payload.get("take_profit")
    if isinstance(tp, dict):
        tp["fallback_sl_pct"] = capped_pct
        tp["fallback_max_sl_pct"] = _FALLBACK_HARD_MAX_SL_PCT
    elif isinstance(tp, list):
        for item in tp:
            if isinstance(item, dict):
                item["fallback_sl_pct"] = capped_pct
                item["fallback_max_sl_pct"] = _FALLBACK_HARD_MAX_SL_PCT
    payload["fallback_target_geometry_capped"] = True
    payload["fallback_edge_geometry_repaired"] = True
    payload["reason"] = str(payload.get("reason") or "fallback_entry") + " [fallback_target_geometry_capped]"
    return payload, True, old_sl_pct, capped_pct


def _hard_block_illiquid_policy(*args: Any, **kwargs: Any) -> Optional[dict[str, Any]]:
    sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
    symbol = _symbol_from_sig(sig)
    df = kwargs.get("df") if "df" in kwargs else (args[0] if args else None)
    action = str(kwargs.get("action") or "enter_long").strip().lower()
    side = "short" if action == "enter_short" else "long"
    if df is None:
        return None
    try:
        from bot.competitive_profitability_policy import get_competitive_profitability_policy
    except Exception:
        try:
            from competitive_profitability_policy import get_competitive_profitability_policy  # type: ignore
        except Exception:
            return None
    try:
        profile = get_competitive_profitability_policy().profile_entry(df=df, side=side)
        if not getattr(profile, "liquidity_ok", True):
            reason = str(getattr(profile, "liquidity_reason", "illiquid_policy_blocked") or "illiquid_policy_blocked")
            detail = f"{_ILLQUID_POLICY_TEXT}: {reason}"
            logger.warning(
                "FORCED_FALLBACK_ILLIQUID_POLICY_HARD_BLOCK marker=20260703u symbol=%s side=%s reason=%s action=hold_skip_before_execute",
                symbol,
                side,
                reason,
            )
            print(
                f"[NIJA-PRINT] FORCED_FALLBACK_ILLIQUID_POLICY_HARD_BLOCK marker=20260703u symbol={symbol} reason={reason}",
                flush=True,
            )
            return _hold_skip(symbol, reason="fallback_illiquid_policy_blocked", stage="competitive_profitability_policy", detail=detail)
    except Exception:
        return None
    return None


def _cache_key(self_obj: Any, sig: Any, snapshot: Any, action: Any, symbol: str) -> tuple[int, int, int, str, str]:
    return (id(self_obj), id(sig), id(snapshot), str(action or ""), symbol)


def _cache_get(key: tuple[int, int, int, str, str]) -> Optional[dict[str, Any]]:
    now = time.time()
    with _CACHE_LOCK:
        item = _PAYLOAD_CACHE.get(key)
        if not item:
            return None
        ts, payload = item
        if now - ts > _CACHE_TTL_S:
            _PAYLOAD_CACHE.pop(key, None)
            return None
        return deepcopy(payload)


def _cache_set(key: tuple[int, int, int, str, str], payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    with _CACHE_LOCK:
        _PAYLOAD_CACHE[key] = (time.time(), deepcopy(payload))
        if len(_PAYLOAD_CACHE) > 128:
            oldest = sorted(_PAYLOAD_CACHE.items(), key=lambda item: item[1][0])[:32]
            for old_key, _ in oldest:
                _PAYLOAD_CACHE.pop(old_key, None)


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_build_forced_fallback_entry_analysis", None)
    if not callable(original):
        return False
    if _wrapper_chain_has_attr(original, _WRAP_ATTR):
        _PATCHED = True
        return True

    def _patched_build_forced_fallback_entry_analysis(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
        snapshot = kwargs.get("snapshot") if "snapshot" in kwargs else (args[2] if len(args) > 2 else None)
        action = kwargs.get("action") if "action" in kwargs else (args[3] if len(args) > 3 else "")
        symbol = _symbol_from_sig(sig)
        key = _cache_key(self, sig, snapshot, action, symbol)

        cached = _cache_get(key)
        if cached is not None:
            logger.info("FORCED_FALLBACK_PAYLOAD_CACHE_HIT marker=20260703u symbol=%s action=%s duplicate_build_prevented=true", symbol, action)
            return cached

        hard_block = _hard_block_illiquid_policy(*args, **kwargs)
        if hard_block is not None:
            _cache_set(key, hard_block)
            return hard_block

        try:
            payload = original(self, *args, **kwargs)
            payload, changed, old_pct, new_pct = _cap_payload_geometry(payload)
            if changed:
                logger.critical(
                    "FORCED_FALLBACK_PAYLOAD_GEOMETRY_NORMALIZED marker=20260703u symbol=%s old_sl_pct=%.4f new_sl_pct=%.4f",
                    symbol,
                    old_pct,
                    new_pct,
                )
                print(
                    f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_GEOMETRY_NORMALIZED marker=20260703u | symbol={symbol} "
                    f"old_sl_pct={old_pct * 100.0:.3f}% new_sl_pct={new_pct * 100.0:.3f}%",
                    flush=True,
                )
            payload = _enforce_fallback_positive_ev(payload, sig=sig, symbol=symbol)
            _cache_set(key, payload)
            return payload
        except ValueError as exc:
            message = str(exc)
            if _ILLQUID_POLICY_TEXT in message or "competitive profitability policy" in message:
                logger.warning(
                    "FORCED_FALLBACK_PAYLOAD_REPAIR_SKIPPED marker=20260703u symbol=%s reason=%s action=hold_skip_before_execute",
                    symbol,
                    message,
                )
                print(
                    f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_SKIPPED marker=20260703u symbol={symbol} reason=illiquid_policy_block",
                    flush=True,
                )
                payload = _hold_skip(symbol, reason="fallback_illiquid_policy_blocked", stage="competitive_profitability_policy", detail=message)
                _cache_set(key, payload)
                return payload
            if "fallback positive-EV prefilter blocked execution" in message:
                logger.warning(
                    "FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703u symbol=%s detail=%s action=hold_skip_before_execute",
                    symbol,
                    message,
                )
                payload = _hold_skip(symbol, reason="fallback_positive_ev_prefilter_blocked", stage="fallback_positive_ev_prefilter", detail=message)
                _cache_set(key, payload)
                return payload
            raise

    setattr(_patched_build_forced_fallback_entry_analysis, _WRAP_ATTR, True)
    setattr(_patched_build_forced_fallback_entry_analysis, "__wrapped__", original)
    setattr(cls, "_build_forced_fallback_entry_analysis", _patched_build_forced_fallback_entry_analysis)
    _PATCHED = True
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED marker=20260703u module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED marker=20260703u | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
            patched = _install_on_module(module) or patched
    return patched


def _start_module_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            time.sleep(1.0)
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_COMPLETE marker=20260703u patched=%s patched_any=%s", _PATCHED, patched_any)

    threading.Thread(target=_monitor, name="forced-fallback-payload-repair-monitor", daemon=True).start()
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_STARTED marker=20260703u")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_module_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE marker=20260703u already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE marker=20260703u patched=%s", _PATCHED)
