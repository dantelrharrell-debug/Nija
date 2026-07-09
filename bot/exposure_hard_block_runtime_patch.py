from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.exposure_hard_block_runtime_patch")

_MARKER = "EXPOSURE_HARD_BLOCK_RUNTIME_PATCHED marker=20260706g"
_IMPORT_FLAG = "_NIJA_EXPOSURE_HARD_BLOCK_RUNTIME_IMPORT_HOOK_V20260706G"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}

_TARGETS = {
    "bot.execution_engine",
    "execution_engine",
    "bot.execution_pipeline",
    "execution_pipeline",
    "bot.ai_intelligence_hub",
    "ai_intelligence_hub",
    "bot.nija_apex_strategy_v71",
    "nija_apex_strategy_v71",
    "bot.regime_strategy_bridge",
    "regime_strategy_bridge",
    "bot.kraken_error_taxonomy",
    "kraken_error_taxonomy",
}


def _truthy_env(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _norm_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _norm_side(value: Any) -> str:
    side = str(value or "").strip().lower()
    if side == "long":
        return "buy"
    if side == "short":
        return "sell"
    return side


def _is_entry_like(*, side: Any = "", action: Any = "", intent_type: Any = "", reduce_only: Any = False, position_effect: Any = "") -> bool:
    if bool(reduce_only):
        return False
    effect = str(position_effect or "").strip().lower()
    if effect in {"close", "close_only", "reduce", "reduce_only", "exit"}:
        return False
    intent = str(intent_type or "").strip().lower()
    if intent in {"reduce", "exit", "close", "close_only"}:
        return False
    action_text = str(action or "").strip().lower()
    if action_text in {"exit", "close", "reduce", "sell_to_close", "exit_long", "exit_short"}:
        return False
    if action_text in {"enter_long", "buy", "open_long", "enter_short", "short", "open_short"}:
        return True
    side_text = _norm_side(side)
    if side_text == "buy":
        return True
    if side_text == "sell" and intent == "entry":
        return True
    return False


def _capital_authority_usable() -> float:
    best = 0.0
    for mod_name in ("bot.capital_authority", "capital_authority"):
        try:
            mod = __import__(mod_name, fromlist=["get_capital_authority"])
            getter = getattr(mod, "get_capital_authority", None)
            if not callable(getter):
                continue
            ca = getter()
            for attr in ("get_usable_capital", "usable_capital", "total_capital", "real_capital"):
                try:
                    value = getattr(ca, attr, None)
                    value = value() if callable(value) else value
                    best = max(best, _float(value, 0.0))
                except Exception:
                    pass
        except Exception:
            pass
    return best


def _risk_engine_from(candidate: Any = None) -> Any | None:
    engine = getattr(candidate, "_pre_trade_risk_engine", None) if candidate is not None else None
    if engine is not None:
        return engine
    try:
        mod = __import__("bot.execution_pipeline", fromlist=["get_execution_pipeline"])
    except Exception:
        try:
            mod = __import__("execution_pipeline", fromlist=["get_execution_pipeline"])
        except Exception:
            return None
    getter = getattr(mod, "get_execution_pipeline", None)
    if not callable(getter):
        return None
    try:
        pipeline = getter()
        return getattr(pipeline, "_pre_trade_risk_engine", None)
    except Exception:
        return None


def _available_balance_from(request: Any = None, fallback: Any = None) -> float:
    for obj in (request, fallback):
        if obj is None:
            continue
        for attr in ("available_balance_usd", "buying_power_usd", "spendable_balance_usd", "cash_usd"):
            value = getattr(obj, attr, None)
            if value is not None:
                amount = _float(value, 0.0)
                if amount > 0:
                    return amount
        if isinstance(obj, dict):
            for key in ("available_balance_usd", "buying_power_usd", "spendable_balance_usd", "cash_usd"):
                if key in obj:
                    amount = _float(obj.get(key), 0.0)
                    if amount > 0:
                        return amount
    return _capital_authority_usable()


def _pretrade_global_exposure_block(
    *,
    engine: Any,
    account_id: Any,
    symbol: Any,
    side: Any,
    size_usd: Any,
    available_balance_usd: Any,
) -> tuple[bool, str, dict[str, Any]]:
    if engine is None or not callable(getattr(engine, "assess", None)):
        return False, "", {}
    size = _float(size_usd, 0.0)
    if size <= 0:
        # Zero-size entry: the early zero-size guard in execute_entry catches this
        # path cleanly.  Return not-blocked so the original function can log the
        # proper breadcrumb rather than silently swallowing it here.
        return False, "", {}
    try:
        decision = engine.assess(
            account_id=str(account_id or "master"),
            symbol=_norm_symbol(symbol),
            size_usd=size,
            available_balance_usd=_float(available_balance_usd, 0.0),
        )
    except Exception as exc:
        logger.debug("GLOBAL_EXPOSURE_PRECHECK_SKIPPED assess_error=%s", exc)
        return False, "", {}
    approved = bool(getattr(decision, "approved", False))
    reason = str(getattr(decision, "reason", "") or "")
    details = dict(getattr(decision, "details", {}) or {})
    reason_upper = reason.upper()
    if not approved and ("GLOBAL_EXPOSURE_CAP" in reason_upper or "EXPOSURE_CAP" in reason_upper):
        return True, reason or "GLOBAL_EXPOSURE_CAP", details
    return False, "", details


def _patch_execution_engine(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute_entry", None)
    if not callable(original) or getattr(original, "_nija_exposure_hard_block_wrapped", False):
        return False

    @wraps(original)
    def execute_entry(self: Any, *args: Any, **kwargs: Any):
        if not _truthy_env("NIJA_GLOBAL_EXPOSURE_PRE_EXECUTION_BLOCK", "true"):
            return original(self, *args, **kwargs)
        symbol = kwargs.get("symbol", args[0] if len(args) > 0 else "")
        side = kwargs.get("side", args[1] if len(args) > 1 else "")
        size_usd = (
            kwargs.get("position_size")
            or kwargs.get("size_usd")
            or kwargs.get("notional_usd")
            or (args[2] if len(args) > 2 else 0.0)
        )
        account_id = kwargs.get("account_id") or getattr(self, "account_id", None) or "master"
        available = (
            kwargs.get("available_balance_usd")
            or kwargs.get("spendable_balance_usd")
            or _available_balance_from(fallback=self)
        )
        if _is_entry_like(side=side, action=kwargs.get("action", ""), intent_type=kwargs.get("intent_type", "entry")):
            blocked, reason, details = _pretrade_global_exposure_block(
                engine=_risk_engine_from(self),
                account_id=account_id,
                symbol=symbol,
                side=side,
                size_usd=size_usd,
                available_balance_usd=available,
            )
            if blocked:
                logger.warning(
                    "ENTRY_SKIPPED_GLOBAL_EXPOSURE_CAP_PRECHECK marker=20260706g surface=ExecutionEngine.execute_entry account=%s symbol=%s side=%s requested_usd=%.2f reason=%s headroom_usd=%.2f cap_usd=%.2f current_total_usd=%.2f",
                    account_id,
                    _norm_symbol(symbol),
                    side,
                    _float(size_usd, 0.0),
                    reason,
                    _float(details.get("headroom_usd"), 0.0),
                    _float(details.get("cap_usd"), 0.0),
                    _float(details.get("current_total_exposure_usd"), 0.0),
                )
                # Emit a flushed breadcrumb so operators can distinguish a
                # terminal risk hard block from a broker/exchange rejection.
                # This must NOT be recorded as an exchange order rejection
                # (doing so would create an EMERGENCY_STOP feedback loop).
                print(
                    f"[NIJA-PRINT] TERMINAL_RISK_HARD_BLOCK marker=20260706g "
                    f"surface=ExecutionEngine.execute_entry "
                    f"account={account_id} symbol={_norm_symbol(symbol)} side={side} "
                    f"reason={reason} "
                    f"headroom_usd={_float(details.get('headroom_usd'), 0.0):.2f} "
                    f"cap_usd={_float(details.get('cap_usd'), 0.0):.2f}",
                    flush=True,
                )
                return None
        return original(self, *args, **kwargs)

    setattr(execute_entry, "_nija_exposure_hard_block_wrapped", True)
    setattr(cls, "execute_entry", execute_entry)
    logger.warning("%s class=ExecutionEngine", _MARKER)
    return True


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    PipelineResult = getattr(module, "PipelineResult", None)
    if not isinstance(cls, type) or PipelineResult is None:
        return False
    original = getattr(cls, "execute", None)
    if not callable(original) or getattr(original, "_nija_exposure_hard_block_wrapped", False):
        return False

    @wraps(original)
    def execute(self: Any, request: Any):
        if _truthy_env("NIJA_GLOBAL_EXPOSURE_PIPELINE_PREFLIGHT", "true"):
            try:
                side = getattr(request, "side", "")
                intent_type = getattr(request, "intent_type", "entry")
                if _is_entry_like(
                    side=side,
                    action=getattr(request, "action", ""),
                    intent_type=intent_type,
                    reduce_only=getattr(request, "reduce_only", False),
                    position_effect=getattr(request, "position_effect", ""),
                ):
                    engine = _risk_engine_from(self)
                    available = _available_balance_from(request)
                    blocked, reason, details = _pretrade_global_exposure_block(
                        engine=engine,
                        account_id=getattr(request, "account_id", "master"),
                        symbol=getattr(request, "symbol", ""),
                        side=side,
                        size_usd=getattr(request, "size_usd", 0.0),
                        available_balance_usd=available,
                    )
                    if blocked:
                        logger.warning(
                            "PIPELINE_ENTRY_SKIPPED_GLOBAL_EXPOSURE_CAP marker=20260706g account=%s symbol=%s side=%s requested_usd=%.2f reason=%s headroom_usd=%.2f",
                            getattr(request, "account_id", "master"),
                            _norm_symbol(getattr(request, "symbol", "")),
                            side,
                            _float(getattr(request, "size_usd", 0.0), 0.0),
                            reason,
                            _float(details.get("headroom_usd"), 0.0),
                        )
                        print(
                            f"[NIJA-PRINT] TERMINAL_RISK_HARD_BLOCK marker=20260706g "
                            f"surface=ExecutionPipeline.execute "
                            f"symbol={_norm_symbol(getattr(request, 'symbol', ''))} side={side} "
                            f"reason={reason} "
                            f"headroom_usd={_float(details.get('headroom_usd'), 0.0):.2f}",
                            flush=True,
                        )
                        return PipelineResult(
                            success=False,
                            symbol=getattr(request, "symbol", ""),
                            side=side,
                            size_usd=_float(getattr(request, "size_usd", 0.0), 0.0),
                            broker="internal_risk",
                            latency_ms=0.0,
                            error=f"PreTradeRiskEngine reject: {reason}",
                        )
            except Exception as exc:
                logger.debug("PIPELINE_GLOBAL_EXPOSURE_PREFLIGHT_SKIPPED err=%s", exc)
        return original(self, request)

    setattr(execute, "_nija_exposure_hard_block_wrapped", True)
    setattr(cls, "execute", execute)
    logger.warning("%s class=ExecutionPipeline", _MARKER)
    return True


def _patch_ai_hub(module: ModuleType) -> bool:
    cls = getattr(module, "AIIntelligenceHub", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "evaluate_trade", None)
    if not callable(original) or getattr(original, "_nija_terminal_hard_block_wrapped", False):
        return False

    @wraps(original)
    def evaluate_trade(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        reason = " ".join(
            str(getattr(result, attr, "") or "")
            for attr in ("exposure_rejection_reason", "ai_reason", "reason")
        ).lower()
        hard_block = (
            getattr(result, "exposure_allowed", True) is False
            and ("hard" in reason or "sector" in reason or "exposure" in reason)
        ) or "hard_sector_limit_block" in reason or "terminal_risk_hard_block" in reason
        if hard_block:
            for attr, value in (
                ("exposure_allowed", False),
                ("ai_approved", False),
                ("approved", False),
                ("allowed", False),
                ("trade_allowed", False),
                ("ai_score", 0.0),
                ("allocated_capital", 0.0),
                ("correlation_adjusted_size_pct", 0.0),
            ):
                try:
                    setattr(result, attr, value)
                except Exception:
                    pass
            try:
                # Normalize reason: strip duplicate terminal_risk_hard_block tokens
                # so the stored ai_reason is a clean single-prefix string.
                _raw_reason = str(reason or "hard risk block").strip()
                _clean_tokens = []
                _seen: set = set()
                for _part in _raw_reason.split():
                    _key = _part.lower().strip(",;:")
                    if _key not in _seen:
                        _clean_tokens.append(_part)
                        _seen.add(_key)
                _clean_reason = " ".join(_clean_tokens)
                # Determine canonical enum tag.
                if "sector" in _clean_reason or "hard_sector_limit" in _clean_reason:
                    _canonical = "SECTOR_EXPOSURE_LIMIT_EXCEEDED"
                elif "terminal_risk_hard_block" in _clean_reason or "entry_blocked" in _clean_reason:
                    _canonical = "ENTRY_BLOCKED_TERMINAL_RISK_HARD_BLOCK"
                else:
                    _canonical = "ENTRY_BLOCKED_TERMINAL_RISK_HARD_BLOCK"
                setattr(result, "ai_reason", _canonical)
                setattr(result, "terminal_risk_detail", _clean_reason)
            except Exception:
                pass
            logger.critical(
                "AI_HUB_TERMINAL_RISK_HARD_BLOCK_ENFORCED marker=20260706g symbol=%s side=%s reason=%s",
                args[0] if args else kwargs.get("symbol", ""),
                args[1] if len(args) > 1 else kwargs.get("side", ""),
                reason,
            )
        return result

    setattr(evaluate_trade, "_nija_terminal_hard_block_wrapped", True)
    setattr(cls, "evaluate_trade", evaluate_trade)
    logger.warning("%s class=AIIntelligenceHub", _MARKER)
    return True


def _contains_terminal_hard_block(value: Any) -> bool:
    text = str(value or "").lower()
    return "terminal_risk_hard_block" in text or "hard_sector_limit_block" in text


def _patch_apex_strategy(module: ModuleType) -> bool:
    patched = False
    for cls_name in ("NIJAApexStrategyV71", "NIJAApexStrategy", "ApexStrategy"):
        cls = getattr(module, cls_name, None)
        if not isinstance(cls, type):
            continue
        original = getattr(cls, "analyze_market", None)
        if not callable(original) or getattr(original, "_nija_terminal_hard_block_wrapped", False):
            continue

        @wraps(original)
        def analyze_market(self: Any, *args: Any, **kwargs: Any):
            result = original(self, *args, **kwargs)
            try:
                if isinstance(result, dict):
                    haystack = " ".join(str(v) for v in result.values())
                    meta = result.get("metadata")
                    if meta:
                        haystack += " " + str(meta)
                    if _contains_terminal_hard_block(haystack):
                        symbol = result.get("symbol") or kwargs.get("symbol") or (args[0] if args else "")
                        reason = result.get("reason") or result.get("filter_stage") or "terminal_risk_hard_block"
                        blocked = dict(result)
                        blocked.update(
                            {
                                "action": "hold",
                                "allowed": False,
                                "passed_gate": False,
                                "signal": False,
                                "position_size": 0.0,
                                "score": 0.0,
                                "reason": "ENTRY_BLOCKED_TERMINAL_RISK_HARD_BLOCK",
                                "filter_stage": "terminal_risk_hard_block",
                                "terminal_risk_detail": str(reason or ""),
                            }
                        )
                        logger.critical(
                            "APEX_SIGNAL_CONVERTED_TO_HOLD_TERMINAL_RISK marker=20260706g symbol=%s reason=%s",
                            symbol,
                            reason,
                        )
                        return blocked
            except Exception as exc:
                logger.debug("APEX_TERMINAL_RISK_POSTPROCESS_SKIPPED err=%s", exc)
            return result

        setattr(analyze_market, "_nija_terminal_hard_block_wrapped", True)
        setattr(cls, "analyze_market", analyze_market)
        patched = True
    if patched:
        logger.warning("%s module=%s apex_strategy=true", _MARKER, getattr(module, "__name__", ""))
    return patched


def _patch_regime_bridge(module: ModuleType) -> bool:
    cls = getattr(module, "RegimeStrategyBridge", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_normalise", None)
    if not callable(original) or getattr(original, "_nija_regime_enum_normalizer_wrapped", False):
        return False

    def _normalise(regime: Any) -> str:
        try:
            key = original(regime)
        except Exception:
            key = str(regime or "weak_trend")
        key = str(key or "weak_trend").strip().lower().replace(" ", "_")
        key = key.replace("marketregime.", "").replace("regimetype.", "")
        if "." in key:
            key = key.rsplit(".", 1)[-1]
        aliases = {
            "trend": "trending",
            "trending_market": "trending",
            "range": "ranging",
            "sideways": "ranging",
            "volatile_market": "volatile",
            "strongtrend": "strong_trend",
            "weaktrend": "weak_trend",
            "meanreversion": "mean_reversion",
            "volatilityexplosion": "volatility_explosion",
        }
        return aliases.get(key, key)

    setattr(_normalise, "_nija_regime_enum_normalizer_wrapped", True)
    setattr(cls, "_normalise", staticmethod(_normalise))
    logger.warning("%s class=RegimeStrategyBridge enum_normalizer=true", _MARKER)
    return True


def _patch_kraken_taxonomy(module: ModuleType) -> bool:
    original = getattr(module, "classify_kraken_error", None)
    Taxonomy = getattr(module, "KrakenErrorTaxonomy", None)
    Category = getattr(module, "KrakenErrorCategory", None)
    Policy = getattr(module, "KrakenRetryPolicy", None)
    if not callable(original) or Taxonomy is None or Category is None or Policy is None:
        return False
    if getattr(original, "_nija_internal_risk_taxonomy_wrapped", False):
        return False

    @wraps(original)
    def classify_kraken_error(error_text: object):
        raw = "" if error_text is None else str(error_text)
        low = raw.lower()
        if any(
            marker in low
            for marker in (
                "pretraderiskengine reject",
                "global_exposure_cap",
                "terminal_risk_hard_block",
                "hard_sector_limit_block",
                "entry_skipped_global_exposure_cap",
            )
        ):
            logger.warning("NIJA_INTERNAL_RISK_BLOCK_CLASSIFIED marker=20260706g raw=%r", raw)
            return Taxonomy(
                category=Category.ORDER,
                policy=Policy.STOP,
                canonical_code="NIJA_INTERNAL_RISK_BLOCK",
                retry_delay_s=0.0,
                max_retries=0,
                remediation="Reduce/close existing exposure or wait for exits before opening new entries.",
                raw_error=raw,
            )
        return original(error_text)

    setattr(classify_kraken_error, "_nija_internal_risk_taxonomy_wrapped", True)
    setattr(module, "classify_kraken_error", classify_kraken_error)
    logger.warning("%s module=%s taxonomy=true", _MARKER, getattr(module, "__name__", ""))
    return True


def _patch_module(module: ModuleType) -> bool:
    name = getattr(module, "__name__", "")
    patched = False
    try:
        if name in {"bot.execution_engine", "execution_engine"}:
            patched = _patch_execution_engine(module) or patched
        elif name in {"bot.execution_pipeline", "execution_pipeline"}:
            patched = _patch_execution_pipeline(module) or patched
        elif name in {"bot.ai_intelligence_hub", "ai_intelligence_hub"}:
            patched = _patch_ai_hub(module) or patched
        elif name in {"bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"}:
            patched = _patch_apex_strategy(module) or patched
        elif name in {"bot.regime_strategy_bridge", "regime_strategy_bridge"}:
            patched = _patch_regime_bridge(module) or patched
        elif name in {"bot.kraken_error_taxonomy", "kraken_error_taxonomy"}:
            patched = _patch_kraken_taxonomy(module) or patched
    except Exception as exc:
        logger.warning("EXPOSURE_HARD_BLOCK_RUNTIME_PATCH_FAILED marker=20260706g module=%s err=%s", name, exc)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name in tuple(_TARGETS):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    if not _truthy_env("NIJA_EXPOSURE_HARD_BLOCK_RUNTIME_PATCH", "true"):
        logger.warning("EXPOSURE_HARD_BLOCK_RUNTIME_PATCH_DISABLED marker=20260706g")
        return
    _try_patch_loaded()
    if getattr(builtins, _IMPORT_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name in _TARGETS or any(str(name).endswith(target.split(".")[-1]) for target in _TARGETS):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("EXPOSURE_HARD_BLOCK_IMPORT_HOOK_FAILED marker=20260706g name=%s err=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_FLAG, True)
    logger.warning("EXPOSURE_HARD_BLOCK_RUNTIME_IMPORT_HOOK marker=20260706g installed=true")


def install() -> None:
    install_import_hook()
