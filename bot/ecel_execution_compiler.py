"""
NIJA ECEL (Execution Contract Enforcement Layer)
=================================================

ECEL is a pre-trade compiler that converts a high-level order intent into an
exchange-valid order payload with deterministic rejection reasons.

Goals
-----
1. Maintain a canonical Coinbase + Kraken contract schema map.
2. Reserve balance before dispatch to avoid overlapping capital commitments.
3. Compile quantity and price to exchange step-size and precision rules.
4. Produce deterministic pre-trade rejections before a broker API call.
"""

from __future__ import annotations

import logging
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Dict, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("nija.ecel")


@dataclass(frozen=True)
class ContractRule:
    """Canonical exchange contract rule for one broker/symbol pair."""

    broker: str
    symbol: str
    base_asset: str
    quote_asset: str
    min_notional_usd: float
    min_base_size: float
    base_step_size: float
    price_step_size: float
    base_precision: int
    price_precision: int
    max_base_size: Optional[float] = None


@dataclass
class CompileRequest:
    """High-level pre-trade request consumed by ECEL."""

    broker: str
    symbol: str
    side: str
    order_type: str
    desired_notional_usd: float
    available_balance_usd: Optional[float] = None
    price_hint_usd: Optional[float] = None
    account_id: str = "default"


@dataclass
class CompileResult:
    """Output of ECEL compile pass."""

    accepted: bool
    reason: str
    broker: str
    symbol: str
    compiled_notional_usd: float = 0.0
    compiled_base_size: Optional[float] = None
    compiled_price_usd: Optional[float] = None
    reservation_id: Optional[str] = None
    rule: Optional[ContractRule] = None
    diagnostics: Dict[str, float] = field(default_factory=dict)


class ContractSchemaMap:
    """Canonical symbol constraints map for Coinbase and Kraken."""

    def __init__(self) -> None:
        self._rules: Dict[Tuple[str, str], ContractRule] = {}
        self._lock = threading.Lock()
        self._last_refresh_ts: float = 0.0
        self._refresh_interval_s: float = float(os.getenv("ECEL_SCHEMA_REFRESH_INTERVAL_S", "900"))
        self._http_timeout_s: float = float(os.getenv("ECEL_SCHEMA_HTTP_TIMEOUT_S", "5"))
        self._live_refresh_enabled: bool = (
            os.getenv("ECEL_ENABLE_LIVE_SCHEMA_REFRESH", "true").strip().lower() in ("1", "true", "yes")
        )
        self._last_refresh_result: Dict[str, int] = {"coinbase": 0, "kraken": 0}
        self._last_refresh_error: str = ""
        self._seed_defaults()

    def get_rule(self, broker: str, symbol: str) -> Optional[ContractRule]:
        key = (self._norm_broker(broker), self._norm_symbol(symbol))
        with self._lock:
            rule = self._rules.get(key)
            if rule is not None:
                return rule
            # Try alias translation (Kraken XBT <-> BTC)
            alias_symbol = self._alias_symbol(self._norm_broker(broker), key[1])
            return self._rules.get((key[0], alias_symbol))

    def upsert_rule(self, rule: ContractRule) -> None:
        key = (self._norm_broker(rule.broker), self._norm_symbol(rule.symbol))
        with self._lock:
            self._rules[key] = rule

    def as_dict(self) -> Dict[str, Dict[str, dict]]:
        out: Dict[str, Dict[str, dict]] = {}
        with self._lock:
            for (broker, symbol), rule in self._rules.items():
                out.setdefault(broker, {})[symbol] = {
                    "base_asset": rule.base_asset,
                    "quote_asset": rule.quote_asset,
                    "min_notional_usd": rule.min_notional_usd,
                    "min_base_size": rule.min_base_size,
                    "base_step_size": rule.base_step_size,
                    "price_step_size": rule.price_step_size,
                    "base_precision": rule.base_precision,
                    "price_precision": rule.price_precision,
                    "max_base_size": rule.max_base_size,
                }
        return out

    def refresh_if_due(self, target_broker: Optional[str] = None) -> None:
        """Refresh live schemas when stale; no-op when disabled."""
        if not self._live_refresh_enabled:
            return

        now = time.time()
        if (now - self._last_refresh_ts) < self._refresh_interval_s:
            return
        self.refresh_from_public_endpoints(target_broker=target_broker)

    def refresh_from_public_endpoints(self, target_broker: Optional[str] = None) -> Dict[str, int]:
        """Fetch public market metadata and update canonical schema map.

        Uses unauthenticated endpoints only; failures never clear existing rules.
        """
        target = (target_broker or "").strip().lower()
        updated = {"coinbase": 0, "kraken": 0}

        try:
            if target in ("", "coinbase"):
                updated["coinbase"] = self._refresh_coinbase()
            if target in ("", "kraken"):
                updated["kraken"] = self._refresh_kraken()
            self._last_refresh_ts = time.time()
            self._last_refresh_result = updated.copy()
            self._last_refresh_error = ""
        except Exception as exc:
            self._last_refresh_error = str(exc)
            logger.warning("ECEL schema refresh failed: %s", exc)

        if updated["coinbase"] or updated["kraken"]:
            logger.info(
                "ECEL schema refresh complete | coinbase=%d rules | kraken=%d rules",
                updated["coinbase"],
                updated["kraken"],
            )
        return updated

    def get_refresh_health(self) -> Dict[str, object]:
        """Return last refresh timestamps/results for observability."""
        with self._lock:
            coinbase_rules = sum(1 for (broker, _symbol) in self._rules.keys() if broker == "coinbase")
            kraken_rules = sum(1 for (broker, _symbol) in self._rules.keys() if broker == "kraken")
        return {
            "enabled": self._live_refresh_enabled,
            "last_refresh_ts": self._last_refresh_ts,
            "last_refresh_result": dict(self._last_refresh_result),
            "last_refresh_error": self._last_refresh_error,
            "configured_interval_s": self._refresh_interval_s,
            "coinbase_rules": coinbase_rules,
            "kraken_rules": kraken_rules,
        }

    @staticmethod
    def _norm_broker(broker: str) -> str:
        return (broker or "unknown").strip().lower()

    @staticmethod
    def _norm_symbol(symbol: str) -> str:
        s = (symbol or "").strip().upper()
        return s.replace("/", "-")

    @staticmethod
    def _alias_symbol(broker: str, symbol: str) -> str:
        if broker == "kraken":
            return symbol.replace("BTC", "XBT") if "BTC" in symbol else symbol.replace("XBT", "BTC")
        return symbol

    @staticmethod
    def _parse_precision_from_step(step: float) -> int:
        d = Decimal(str(step)).normalize()
        exponent = d.as_tuple().exponent
        if not isinstance(exponent, int):
            return 0
        return max(0, -exponent)

    @staticmethod
    def _safe_float(value: object, fallback: float = 0.0) -> float:
        try:
            return float(str(value))
        except Exception:
            return fallback

    @staticmethod
    def _normalise_kraken_asset(asset: str) -> str:
        x = (asset or "").upper()
        if x.startswith(("X", "Z")) and len(x) > 3:
            x = x[1:]
        if x == "XBT":
            return "XBT"
        if x == "XXBT":
            return "XBT"
        return x

    def _fetch_json(self, url: str) -> Optional[dict]:
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": "NIJA-ECEL/1.0",
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=self._http_timeout_s) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            logger.debug("ECEL schema fetch failed for %s: %s", url, exc)
            return None

    def _refresh_coinbase(self) -> int:
        data = self._fetch_json("https://api.exchange.coinbase.com/products")
        if not isinstance(data, list):
            return 0

        updated = 0
        for p in data:
            if not isinstance(p, dict):
                continue

            symbol = self._norm_symbol(str(p.get("id") or ""))
            base = str(p.get("base_currency") or "").upper()
            quote = str(p.get("quote_currency") or "").upper()
            if not symbol or not base or not quote:
                continue

            if quote not in ("USD", "USDC"):
                continue

            min_base = self._safe_float(p.get("base_min_size"), 0.0)
            base_step = self._safe_float(p.get("base_increment"), min_base or 0.00000001)
            price_step = self._safe_float(p.get("quote_increment"), 0.01)
            min_notional = self._safe_float(p.get("min_market_funds"), 1.0)

            rule = ContractRule(
                broker="coinbase",
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
                min_notional_usd=max(1.0, min_notional),
                min_base_size=max(base_step, min_base, 0.0),
                base_step_size=max(base_step, 1e-12),
                price_step_size=max(price_step, 1e-12),
                base_precision=self._parse_precision_from_step(max(base_step, 1e-12)),
                price_precision=self._parse_precision_from_step(max(price_step, 1e-12)),
            )
            self.upsert_rule(rule)
            updated += 1
        return updated

    def _refresh_kraken(self) -> int:
        data = self._fetch_json("https://api.kraken.com/0/public/AssetPairs")
        if not isinstance(data, dict):
            return 0
        result = data.get("result")
        if not isinstance(result, dict):
            return 0

        updated = 0
        for pair_info in result.values():
            if not isinstance(pair_info, dict):
                continue

            wsname = str(pair_info.get("wsname") or "")
            altname = str(pair_info.get("altname") or "")
            symbol_src = wsname if wsname else altname
            if not symbol_src:
                continue

            symbol = self._norm_symbol(symbol_src)
            if "-" not in symbol and "/" in symbol_src:
                symbol = self._norm_symbol(symbol_src.replace("/", "-"))

            base = self._normalise_kraken_asset(str(pair_info.get("base") or ""))
            quote = self._normalise_kraken_asset(str(pair_info.get("quote") or ""))
            if quote not in ("USD", "USDC", "ZUSD"):
                continue
            if quote == "ZUSD":
                quote = "USD"

            min_base = self._safe_float(pair_info.get("ordermin"), 0.0)
            min_notional = self._safe_float(pair_info.get("costmin"), 10.0)

            lot_decimals = int(self._safe_float(pair_info.get("lot_decimals"), 8))
            pair_decimals = int(self._safe_float(pair_info.get("pair_decimals"), 2))

            base_step = 10 ** (-max(0, lot_decimals))
            price_step = 10 ** (-max(0, pair_decimals))

            rule = ContractRule(
                broker="kraken",
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
                min_notional_usd=max(10.0, min_notional),
                min_base_size=max(min_base, base_step),
                base_step_size=base_step,
                price_step_size=price_step,
                base_precision=max(0, lot_decimals),
                price_precision=max(0, pair_decimals),
            )
            self.upsert_rule(rule)
            updated += 1
        return updated

    def _seed_defaults(self) -> None:
        # Coinbase samples (step/precision values chosen conservatively).
        defaults = [
            ContractRule("coinbase", "BTC-USD", "BTC", "USD", 1.0, 0.00000001, 0.00000001, 0.01, 8, 2),
            ContractRule("coinbase", "ETH-USD", "ETH", "USD", 1.0, 0.0000001, 0.0000001, 0.01, 7, 2),
            ContractRule("coinbase", "SOL-USD", "SOL", "USD", 1.0, 0.0001, 0.0001, 0.001, 4, 3),
            ContractRule("coinbase", "XRP-USD", "XRP", "USD", 1.0, 0.1, 0.1, 0.0001, 1, 4),
            ContractRule("coinbase", "ADA-USD", "ADA", "USD", 1.0, 0.1, 0.1, 0.0001, 1, 4),
            # Kraken samples (harder min notional floor).
            ContractRule("kraken", "XBT-USD", "XBT", "USD", 10.0, 0.00001, 0.00001, 0.1, 5, 1),
            ContractRule("kraken", "ETH-USD", "ETH", "USD", 10.0, 0.0001, 0.0001, 0.1, 4, 1),
            ContractRule("kraken", "SOL-USD", "SOL", "USD", 10.0, 0.001, 0.001, 0.01, 3, 2),
            ContractRule("kraken", "XRP-USD", "XRP", "USD", 10.0, 1.0, 1.0, 0.0001, 0, 4),
            ContractRule("kraken", "ADA-USD", "ADA", "USD", 10.0, 1.0, 1.0, 0.0001, 0, 4),
        ]
        for rule in defaults:
            self.upsert_rule(rule)


class PreTradeBalanceReservationSystem:
    """Thin wrapper over CapitalReservationManager with deterministic IDs."""

    def __init__(self) -> None:
        self._crm = self._load_crm()

    def reserve(
        self,
        account_id: str,
        broker: str,
        symbol: str,
        amount_usd: float,
        total_balance_usd: float,
    ) -> Tuple[bool, str, Optional[str]]:
        if self._crm is None:
            return True, "reservation-bypassed", None

        can_open, message, _details = self._crm.can_open_position(
            total_balance=total_balance_usd,
            new_position_size=amount_usd,
            account_id=account_id,
        )
        if not can_open:
            return False, message, None

        reservation_id = f"ecel-{uuid.uuid4().hex[:16]}"
        ok = self._crm.reserve_capital(
            position_id=reservation_id,
            amount=amount_usd,
            symbol=symbol,
            account_id=account_id,
            broker=broker,
        )
        if not ok:
            return False, "failed to persist capital reservation", None
        return True, "reserved", reservation_id

    def release(self, reservation_id: Optional[str]) -> None:
        if not reservation_id or self._crm is None:
            return
        self._crm.release_capital(reservation_id)

    @staticmethod
    def _load_crm():
        try:
            from bot.capital_reservation_manager import get_capital_reservation_manager
        except ImportError:
            try:
                from capital_reservation_manager import get_capital_reservation_manager
            except ImportError:
                logger.warning("ECEL: capital reservation manager unavailable")
                return None
        try:
            return get_capital_reservation_manager()
        except Exception as exc:
            logger.warning("ECEL: capital reservation manager failed to initialise: %s", exc)
            return None


class PrecisionCompiler:
    """Compiles base size and price onto broker-supported grids."""

    @staticmethod
    def compile_base_size(raw_base_size: float, rule: ContractRule) -> float:
        raw = Decimal(str(max(0.0, raw_base_size)))
        step = Decimal(str(rule.base_step_size))
        if step <= 0:
            return round(float(raw), rule.base_precision)

        units = (raw / step).to_integral_value(rounding=ROUND_DOWN)
        compiled = (units * step).quantize(Decimal(10) ** -rule.base_precision, rounding=ROUND_DOWN)
        return float(compiled)

    @staticmethod
    def compile_price(raw_price: float, side: str, rule: ContractRule) -> float:
        raw = Decimal(str(max(0.0, raw_price)))
        step = Decimal(str(rule.price_step_size))
        if step <= 0:
            return round(float(raw), rule.price_precision)

        rounding = ROUND_UP if side.lower() == "sell" else ROUND_DOWN
        units = (raw / step).to_integral_value(rounding=rounding)
        compiled = (units * step).quantize(Decimal(10) ** -rule.price_precision, rounding=rounding)
        return float(compiled)


class ECELExecutionCompiler:
    """Main ECEL facade consumed by execution pipeline."""

    def __init__(self) -> None:
        self.schema = ContractSchemaMap()
        self.reservations = PreTradeBalanceReservationSystem()
        self.precision = PrecisionCompiler()

    def compile(self, req: CompileRequest) -> CompileResult:
        broker = (req.broker or "coinbase").lower()
        symbol = req.symbol

        # Keep schema data fresh from public endpoints without blocking every call.
        self.schema.refresh_if_due(target_broker=broker)

        rule = self.schema.get_rule(broker, symbol)
        if rule is None:
            return CompileResult(
                accepted=False,
                reason=f"No contract rule found for {broker}:{symbol}",
                broker=broker,
                symbol=symbol,
            )

        if req.desired_notional_usd <= 0:
            return CompileResult(
                accepted=False,
                reason="Order notional must be greater than zero",
                broker=broker,
                symbol=symbol,
                rule=rule,
            )

        compiled_notional = max(req.desired_notional_usd, rule.min_notional_usd)

        compiled_price = None
        compiled_base = None
        if req.price_hint_usd is not None and req.price_hint_usd > 0:
            compiled_price = self.precision.compile_price(req.price_hint_usd, req.side, rule)
            raw_base = compiled_notional / max(compiled_price, 1e-12)
            compiled_base = self.precision.compile_base_size(raw_base, rule)

            if compiled_base < rule.min_base_size:
                compiled_base = rule.min_base_size
                compiled_base = self.precision.compile_base_size(compiled_base, rule)

            compiled_notional = compiled_base * compiled_price

            if rule.max_base_size is not None and compiled_base > rule.max_base_size:
                return CompileResult(
                    accepted=False,
                    reason=(
                        f"Compiled size {compiled_base:.10f} exceeds max base size "
                        f"{rule.max_base_size:.10f}"
                    ),
                    broker=broker,
                    symbol=symbol,
                    rule=rule,
                )

        reservation_id = None
        if req.available_balance_usd is not None:
            ok, message, reservation_id = self.reservations.reserve(
                account_id=req.account_id,
                broker=broker,
                symbol=symbol,
                amount_usd=compiled_notional,
                total_balance_usd=req.available_balance_usd,
            )
            if not ok:
                return CompileResult(
                    accepted=False,
                    reason=f"Pre-trade reservation rejected: {message}",
                    broker=broker,
                    symbol=symbol,
                    compiled_notional_usd=compiled_notional,
                    compiled_base_size=compiled_base,
                    compiled_price_usd=compiled_price,
                    rule=rule,
                )

        return CompileResult(
            accepted=True,
            reason="accepted",
            broker=broker,
            symbol=symbol,
            compiled_notional_usd=compiled_notional,
            compiled_base_size=compiled_base,
            compiled_price_usd=compiled_price,
            reservation_id=reservation_id,
            rule=rule,
            diagnostics={
                "min_notional_usd": rule.min_notional_usd,
                "min_base_size": rule.min_base_size,
                "base_step_size": rule.base_step_size,
                "price_step_size": rule.price_step_size,
            },
        )

    def release_reservation(self, reservation_id: Optional[str]) -> None:
        self.reservations.release(reservation_id)


_INSTANCE: Optional[ECELExecutionCompiler] = None
_INSTANCE_LOCK = threading.Lock()


def get_ecel_execution_compiler() -> ECELExecutionCompiler:
    """Return process-wide ECEL compiler singleton."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = ECELExecutionCompiler()
    return _INSTANCE
