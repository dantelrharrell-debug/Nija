from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import logging
import os
import sys
import threading
import time
from dataclasses import replace
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.usdt_kraken_ecel_routing_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED_PIPELINE = False
_PATCHED_ECEL = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()

_PATCHED_CORE_LOOP_IDS: set[int] = set()
_CORE_LOOP_HOOK_INSTALLED = False
_LOOP_PATCH_STATE: dict[str, Any] = {
    "thread": None,
    "start_lock": threading.RLock(),
    "silent_strategy_cycles": 0,
    "cycle_seq": 0,
}
_LOOP_LOCAL = threading.local()
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy_env(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _loop_runtime_patch_enabled() -> bool:
    return (
        _truthy_env("NIJA_RUNTIME_LOOP_PATCH_ENABLED", "true")
        and not _truthy_env("NIJA_RUNTIME_LOOP_PATCH_DISABLED")
    )


def _is_usdt_spot(symbol: str) -> bool:
    return str(symbol or "").strip().upper().replace("/", "-").endswith("-USDT")


def _kraken_usdt_rule(module: ModuleType, symbol: str) -> Any:
    ContractRule = getattr(module, "ContractRule")
    s = str(symbol or "").strip().upper().replace("/", "-")
    base = s.split("-", 1)[0]
    kraken_base = "XBT" if base == "BTC" else base
    canonical_symbol = f"{kraken_base}-USDT"
    min_base = 0.00000001
    base_step = 0.00000001
    price_step = 0.01
    price_precision = 2
    if kraken_base in {"XBT", "BTC"}:
        min_base = 0.00001
        base_step = 0.00000001
        price_step = 0.1
        price_precision = 1
    return ContractRule(
        broker="kraken",
        symbol=canonical_symbol,
        base_asset=kraken_base,
        quote_asset="USDT",
        min_notional_usd=10.0,
        min_base_size=min_base,
        base_step_size=base_step,
        price_step_size=price_step,
        base_precision=8,
        price_precision=price_precision,
    )


def _install_on_ecel(module: ModuleType) -> bool:
    global _PATCHED_ECEL
    schema_cls = getattr(module, "ContractSchemaMap", None)
    compiler_cls = getattr(module, "ECELExecutionCompiler", None)
    if not isinstance(schema_cls, type) or not isinstance(compiler_cls, type):
        return False

    original_get_rule = getattr(schema_cls, "get_rule", None)
    if callable(original_get_rule) and not getattr(original_get_rule, "_nija_usdt_kraken_get_rule_wrapped", False):
        def _patched_get_rule(self: Any, broker: str, symbol: str):
            rule = original_get_rule(self, broker, symbol)
            if rule is not None:
                return rule
            if str(broker or "").strip().lower() == "kraken" and _is_usdt_spot(symbol):
                rule = _kraken_usdt_rule(module, symbol)
                try:
                    self.upsert_rule(rule)
                except Exception:
                    pass
                logger.critical("USDT_KRAKEN_ECEL_RULE_REPAIR_APPLIED broker=kraken symbol=%s canonical=%s", symbol, rule.symbol)
                return rule
            return None
        setattr(_patched_get_rule, "_nija_usdt_kraken_get_rule_wrapped", True)
        setattr(schema_cls, "get_rule", _patched_get_rule)

    original_compile = getattr(compiler_cls, "compile", None)
    if callable(original_compile) and not getattr(original_compile, "_nija_usdt_kraken_compile_wrapped", False):
        def _patched_compile(self: Any, req: Any):
            broker = str(getattr(req, "broker", "") or "").strip().lower()
            symbol = str(getattr(req, "symbol", "") or "")
            if broker in {"", "coinbase", "auto"} and _is_usdt_spot(symbol):
                try:
                    req = replace(req, broker="kraken")
                except Exception:
                    setattr(req, "broker", "kraken")
                logger.critical("USDT_KRAKEN_ECEL_ROUTING_REPAIR_APPLIED raw_broker=%s symbol=%s broker=kraken", broker or "unset", symbol)
                print(f"[NIJA-PRINT] USDT_KRAKEN_ECEL_ROUTING_REPAIR_APPLIED | symbol={symbol} broker=kraken", flush=True)
            return original_compile(self, req)
        setattr(_patched_compile, "_nija_usdt_kraken_compile_wrapped", True)
        setattr(compiler_cls, "compile", _patched_compile)

    _PATCHED_ECEL = True
    logger.warning("USDT_KRAKEN_ECEL_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _install_on_pipeline(module: ModuleType) -> bool:
    global _PATCHED_PIPELINE
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original_execute = getattr(cls, "execute", None)
    if not callable(original_execute):
        return False
    if getattr(original_execute, "_nija_usdt_kraken_pipeline_routing_wrapped", False):
        _PATCHED_PIPELINE = True
        return True

    def _patched_execute(self: Any, request: Any, *args: Any, **kwargs: Any):
        try:
            symbol = str(getattr(request, "symbol", "") or "")
            broker = str(getattr(request, "preferred_broker", "") or "").strip().lower()
            if _is_usdt_spot(symbol) and broker in {"", "auto", "coinbase"}:
                request = replace(request, preferred_broker="kraken")
                logger.critical("USDT_KRAKEN_PIPELINE_ROUTING_REPAIR_APPLIED symbol=%s raw_broker=%s broker=kraken", symbol, broker or "unset")
                print(f"[NIJA-PRINT] USDT_KRAKEN_PIPELINE_ROUTING_REPAIR_APPLIED | symbol={symbol} broker=kraken", flush=True)
        except Exception as exc:
            logger.warning("USDT_KRAKEN_PIPELINE_ROUTING_REPAIR skipped err=%s", exc)
        return original_execute(self, request, *args, **kwargs)

    setattr(_patched_execute, "_nija_usdt_kraken_pipeline_routing_wrapped", True)
    setattr(cls, "execute", _patched_execute)
    _PATCHED_PIPELINE = True
    logger.warning("USDT_KRAKEN_PIPELINE_ROUTING_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


class _MaxLevelFilter(logging.Filter):
    def __init__(self, exclusive_max_level: int) -> None:
        super().__init__()
        self.exclusive_max_level = int(exclusive_max_level)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.exclusive_max_level


def _configure_info_stdout_logging() -> None:
    """Route INFO/DEBUG stream logs to stdout while WARNING+ stays on stderr."""
    if not _truthy_env("NIJA_STDOUT_INFO_ROUTING", "true"):
        return
    for logger_obj in (logging.getLogger(), logging.getLogger("nija"), logging.getLogger("nija.core_loop")):
        for handler in list(logger_obj.handlers):
            if getattr(handler, "_nija_stdout_info_split_source", False):
                continue
            if not isinstance(handler, logging.StreamHandler):
                continue
            if getattr(handler, "stream", None) is not sys.stderr:
                continue
            if handler.level not in (logging.NOTSET, logging.DEBUG, logging.INFO):
                continue

            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setLevel(handler.level if handler.level != logging.NOTSET else logging.DEBUG)
            stdout_handler.setFormatter(handler.formatter)
            stdout_handler.addFilter(_MaxLevelFilter(logging.WARNING))
            setattr(stdout_handler, "_nija_stdout_info_split_source", True)
            setattr(handler, "_nija_stdout_info_split_source", True)
            logger_obj.addHandler(stdout_handler)
            handler.setLevel(logging.WARNING)
            logger.warning(
                "STDOUT_INFO_ROUTING_ENABLED logger=%s stderr_handler_level=WARNING",
                logger_obj.name or "root",
            )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def _find_existing_loop_thread() -> Optional[threading.Thread]:
    known = _LOOP_PATCH_STATE.get("thread")
    if isinstance(known, threading.Thread) and known.is_alive():
        return known
    for thread in threading.enumerate():
        if thread.name == "TradingLoop" and thread.is_alive():
            _LOOP_PATCH_STATE["thread"] = thread
            return thread
    return None


def _get_cycle_id(core_module: ModuleType) -> str:
    cid = str(getattr(core_module, "_current_cycle_id", "") or "").strip()
    if cid:
        return cid
    _LOOP_PATCH_STATE["cycle_seq"] = int(_LOOP_PATCH_STATE.get("cycle_seq", 0) or 0) + 1
    return f"runtime-patch-cycle-{_LOOP_PATCH_STATE['cycle_seq']:06d}"


def _patch_execute_action(strategy: Any) -> None:
    apex = getattr(strategy, "apex", None) or strategy
    execute_action = getattr(apex, "execute_action", None)
    if not callable(execute_action):
        return
    if getattr(apex, "_nija_loop_runtime_execute_action_patched", False):
        return

    def _wrapped_execute_action(*args: Any, **kwargs: Any) -> Any:
        ctx = getattr(_LOOP_LOCAL, "cycle_ctx", None)
        if isinstance(ctx, dict):
            ctx["order_seen"] = True

        analysis = args[0] if args else kwargs.get("analysis", {})
        symbol = args[1] if len(args) > 1 else kwargs.get("symbol")
        action = None
        size = 0.0
        price = 0.0
        if isinstance(analysis, dict):
            action = analysis.get("action")
            size = _safe_float(analysis.get("position_size"), 0.0)
            price = _safe_float(analysis.get("entry_price"), 0.0)

        logger.critical(
            "[OrderSubmit] symbol=%s action=%s position_size=$%.2f entry_price=%.8f",
            symbol or "unknown",
            action or "unknown",
            size,
            price,
        )
        try:
            result = execute_action(*args, **kwargs)
        except Exception as exc:
            logger.critical(
                "[OrderResult] symbol=%s success=false exception=%s",
                symbol or "unknown",
                exc,
                exc_info=True,
            )
            raise
        logger.critical("[OrderResult] symbol=%s success=%s", symbol or "unknown", bool(result))
        return result

    setattr(apex, "execute_action", _wrapped_execute_action)
    setattr(apex, "_nija_loop_runtime_execute_action_patched", True)


def _patch_strategy_run_cycle(strategy: Any, core_module: ModuleType) -> None:
    run_cycle = getattr(strategy, "run_cycle", None)
    if not callable(run_cycle):
        return
    if getattr(strategy, "_nija_loop_runtime_run_cycle_patched", False):
        return

    def _wrapped_run_cycle(*args: Any, **kwargs: Any) -> Any:
        _configure_info_stdout_logging()
        _patch_execute_action(strategy)
        cycle_id = _get_cycle_id(core_module)
        broker = getattr(strategy, "broker", None)
        symbols = getattr(strategy, "symbols", None) or []
        ctx = {
            "cycle_id": cycle_id,
            "scan_seen": False,
            "order_seen": False,
            "started_at": time.monotonic(),
        }
        _LOOP_LOCAL.cycle_ctx = ctx
        logger.info(
            "[CycleStart] cycle_id=%s strategy=%s broker=%s broker_connected=%s symbols=%d",
            cycle_id,
            type(strategy).__name__,
            type(broker).__name__ if broker is not None else "none",
            getattr(broker, "connected", None) if broker is not None else None,
            len(symbols) if hasattr(symbols, "__len__") else 0,
        )
        try:
            result = run_cycle(*args, **kwargs)
            elapsed_ms = (time.monotonic() - float(ctx["started_at"])) * 1000.0
            if not bool(ctx.get("scan_seen")):
                _LOOP_PATCH_STATE["silent_strategy_cycles"] = int(_LOOP_PATCH_STATE.get("silent_strategy_cycles", 0) or 0) + 1
                silent_cycles = int(_LOOP_PATCH_STATE["silent_strategy_cycles"])
                limit = max(1, int(float(os.environ.get("NIJA_EXECUTION_SILENT_CYCLE_LIMIT", "5") or "5")))
                message = (
                    f"[ExecutionPathSilent] cycles={silent_cycles} "
                    f"reason=no_run_scan_phase_events_seen cycle_id={cycle_id} "
                    f"strategy={type(strategy).__name__}"
                )
                if silent_cycles >= limit:
                    logger.error(message)
                    if _truthy_env("NIJA_EXECUTION_SILENCE_HARD_FAIL", "true"):
                        raise RuntimeError(message)
                else:
                    logger.warning("%s threshold=%d", message, limit)
            else:
                _LOOP_PATCH_STATE["silent_strategy_cycles"] = 0

            logger.info(
                "[CycleComplete] cycle_id=%s scan_seen=%s order_seen=%s elapsed_ms=%.0f next_interval=%s",
                cycle_id,
                bool(ctx.get("scan_seen")),
                bool(ctx.get("order_seen")),
                elapsed_ms,
                result,
            )
            return result
        finally:
            _LOOP_LOCAL.cycle_ctx = None

    setattr(strategy, "run_cycle", _wrapped_run_cycle)
    setattr(strategy, "_nija_loop_runtime_run_cycle_patched", True)


def _scan_reason(result: Any, symbols: Any, user_mode: bool) -> str:
    if user_mode:
        return "entries_blocked_user_mode"
    if not symbols:
        return "no_symbols_to_scan"
    scored = int(getattr(result, "symbols_scored", 0) or 0)
    entries = int(getattr(result, "entries_taken", 0) or 0)
    blocked = int(getattr(result, "entries_blocked", 0) or 0)
    if entries > 0:
        return "order_path_reached"
    if scored == 0:
        return "no_symbols_scored"
    if blocked > 0:
        return "entries_blocked_by_gates"
    return "scan_complete_no_entry"


def _install_on_core_loop(module: ModuleType) -> bool:
    if not _loop_runtime_patch_enabled():
        return False
    module_id = id(module)
    if module_id in _PATCHED_CORE_LOOP_IDS:
        return True
    _PATCHED_CORE_LOOP_IDS.add(module_id)

    _configure_info_stdout_logging()
    original_start = getattr(module, "start_trading_engine", None)
    original_run = getattr(module, "run_trading_loop", None)
    loop_cls = getattr(module, "NijaCoreLoop", None)

    if callable(original_run):
        def _patched_run_trading_loop(strategy: Any, cycle_secs: int = 150) -> Any:
            _configure_info_stdout_logging()
            _patch_strategy_run_cycle(strategy, module)
            return original_run(strategy, cycle_secs)

        setattr(module, "run_trading_loop", _patched_run_trading_loop)

    if callable(original_start):
        def _patched_start_trading_engine(strategy: Any) -> threading.Thread:
            _configure_info_stdout_logging()
            with _LOOP_PATCH_STATE["start_lock"]:
                existing = _find_existing_loop_thread()
                loop_running = bool(getattr(module, "_loop_running", False))
                if existing is not None or loop_running:
                    logger.warning(
                        "[LoopStartSkipped] reason=already_running thread_alive=%s loop_running=%s strategy=%s",
                        bool(existing and existing.is_alive()),
                        loop_running,
                        type(strategy).__name__,
                    )
                    return existing if existing is not None else threading.current_thread()
                thread = original_start(strategy)
                if isinstance(thread, threading.Thread):
                    _LOOP_PATCH_STATE["thread"] = thread
                return thread

        setattr(module, "start_trading_engine", _patched_start_trading_engine)

    if loop_cls is not None and hasattr(loop_cls, "run_scan_phase"):
        original_scan = getattr(loop_cls, "run_scan_phase")
        if callable(original_scan) and not getattr(loop_cls, "_nija_loop_runtime_scan_patched", False):
            def _patched_run_scan_phase(
                self: Any,
                broker: Any,
                balance: float,
                symbols: list[str],
                open_positions_count: int = 0,
                user_mode: bool = False,
            ) -> Any:
                _configure_info_stdout_logging()
                ctx = getattr(_LOOP_LOCAL, "cycle_ctx", None)
                cycle_id = ctx.get("cycle_id") if isinstance(ctx, dict) else _get_cycle_id(module)
                if isinstance(ctx, dict):
                    ctx["scan_seen"] = True
                logger.info(
                    "[ScannerStart] cycle_id=%s broker=%s connected=%s balance=$%.2f symbols=%d open_positions=%d user_mode=%s",
                    cycle_id,
                    type(broker).__name__ if broker is not None else "none",
                    getattr(broker, "connected", None) if broker is not None else None,
                    _safe_float(balance, 0.0),
                    len(symbols or []),
                    open_positions_count,
                    user_mode,
                )
                result = original_scan(
                    self,
                    broker=broker,
                    balance=balance,
                    symbols=symbols,
                    open_positions_count=open_positions_count,
                    user_mode=user_mode,
                )
                scored = int(getattr(result, "symbols_scored", 0) or 0)
                entries = int(getattr(result, "entries_taken", 0) or 0)
                blocked = int(getattr(result, "entries_blocked", 0) or 0)
                exits = int(getattr(result, "exits_taken", 0) or 0)
                reason = _scan_reason(result, symbols, user_mode)
                logger.info(
                    "[ScannerResult] cycle_id=%s symbols=%d scored=%d entries=%d blocked=%d exits=%d next_interval=%s reason=%s",
                    cycle_id,
                    len(symbols or []),
                    scored,
                    entries,
                    blocked,
                    exits,
                    getattr(result, "next_interval", None),
                    reason,
                )
                logger.info(
                    "[TradeAdmission] cycle_id=%s allowed=%s reason=%s entries=%d blocked=%d scored=%d",
                    cycle_id,
                    entries > 0,
                    reason,
                    entries,
                    blocked,
                    scored,
                )
                return result

            setattr(loop_cls, "run_scan_phase", _patched_run_scan_phase)
            setattr(loop_cls, "_nija_loop_runtime_scan_patched", True)

    logger.warning(
        "LOOP_RUNTIME_REPAIR_APPLIED module=%s duplicate_start_guard=true scanner_telemetry=true silent_path_watchdog=true stdout_info_routing=true",
        getattr(module, "__name__", "<unknown>"),
    )
    return True


class _CoreLoopPatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec: Any) -> Any:
        create = getattr(self._wrapped, "create_module", None)
        if callable(create):
            return create(spec)
        return None

    def exec_module(self, module: Any) -> None:
        self._wrapped.exec_module(module)  # type: ignore[attr-defined]
        if isinstance(module, ModuleType):
            _install_on_core_loop(module)


class _CoreLoopPatchFinder(importlib.abc.MetaPathFinder):
    TARGETS = {"bot.nija_core_loop", "nija_core_loop"}

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname not in self.TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        if isinstance(spec.loader, _CoreLoopPatchLoader):
            return spec
        spec.loader = _CoreLoopPatchLoader(spec.loader)  # type: ignore[arg-type]
        return spec


def _install_core_loop_import_hook() -> None:
    global _CORE_LOOP_HOOK_INSTALLED
    if not _loop_runtime_patch_enabled():
        logger.warning("LOOP_RUNTIME_REPAIR_DISABLED")
        return

    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _install_on_core_loop(module)

    if _CORE_LOOP_HOOK_INSTALLED:
        return
    sys.meta_path.insert(0, _CoreLoopPatchFinder())
    _CORE_LOOP_HOOK_INSTALLED = True
    logger.warning("LOOP_RUNTIME_REPAIR_IMPORT_HOOK_INSTALLED")


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.ecel_execution_compiler", "ecel_execution_compiler"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_ecel(module) or patched
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_pipeline(module) or patched
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_core_loop(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning(
            "USDT_KRAKEN_ECEL_ROUTING_REPAIR_MONITOR_EXPIRED pipeline=%s ecel=%s core_loop=%s",
            _PATCHED_PIPELINE,
            _PATCHED_ECEL,
            bool(_PATCHED_CORE_LOOP_IDS),
        )

    threading.Thread(target=_monitor, name="usdt-kraken-ecel-routing-repair-monitor", daemon=True).start()
    logger.warning("USDT_KRAKEN_ECEL_ROUTING_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _install_core_loop_import_hook()
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning(
                "USDT_KRAKEN_ECEL_ROUTING_REPAIR_INSTALL_COMPLETE already_installed=True pipeline=%s ecel=%s core_loop=%s",
                _PATCHED_PIPELINE,
                _PATCHED_ECEL,
                bool(_PATCHED_CORE_LOOP_IDS),
            )
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.ecel_execution_compiler", "ecel_execution_compiler"}:
                _install_on_ecel(module)
            if name in {"bot.execution_pipeline", "execution_pipeline"}:
                _install_on_pipeline(module)
            if name in {"bot.nija_core_loop", "nija_core_loop"}:
                _install_on_core_loop(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning(
            "USDT_KRAKEN_ECEL_ROUTING_REPAIR_INSTALL_COMPLETE pipeline=%s ecel=%s core_loop=%s",
            _PATCHED_PIPELINE,
            _PATCHED_ECEL,
            bool(_PATCHED_CORE_LOOP_IDS),
        )
