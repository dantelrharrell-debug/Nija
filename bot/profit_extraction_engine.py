"""
NIJA Profit Extraction Engine
================================

Automatically transfers realised profits to three destination buckets:

  1. **Bank**           — fiat withdrawal to the operator's linked bank account.
  2. **Stablecoins**    — converts profits to USDC/USDT on-chain or on-exchange.
  3. **Treasury Wallet**— moves profits to a designated cold-storage wallet for
                          long-term capital preservation.

How it works
------------
1. After a trade closes, call ``record_profit(symbol, pnl_usd)`` to log the
   realised gain.
2. The engine accumulates profits in its internal pool.
3. When either a time-interval or a dollar threshold is crossed, it
   automatically triggers ``extract()`` which splits the extractable profit
   among the three destinations according to the configured fractions.
4. Each extraction is logged with an immutable audit trail.

Default extraction split (configurable at construction):

  * 40 % → Bank
  * 35 % → Stablecoins
  * 25 % → Treasury Wallet

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │              ProfitExtractionEngine                          │
  │                                                              │
  │  record_profit(symbol, pnl_usd)  →  pool grows              │
  │  extract()  →  splits pool → bank / stablecoins / treasury   │
  │  get_report() → dashboard                                    │
  └──────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.profit_extraction_engine import (
        get_profit_extraction_engine, ExtractionConfig
    )

    engine = get_profit_extraction_engine()

    # After a winning trade:
    engine.record_profit("BTC-USD", pnl_usd=250.0)

    # Force an immediate extraction:
    result = engine.extract()
    print(result)

    # Status dashboard:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.profit_extraction_engine")

# ---------------------------------------------------------------------------
# Optional subsystem imports
# ---------------------------------------------------------------------------

try:
    from bot.portfolio_profit_engine import get_portfolio_profit_engine
    _PPE_AVAILABLE = True
except ImportError:
    try:
        from portfolio_profit_engine import get_portfolio_profit_engine
        _PPE_AVAILABLE = True
    except ImportError:
        _PPE_AVAILABLE = False
        get_portfolio_profit_engine = None  # type: ignore
        logger.warning("PortfolioProfitEngine not available — standalone mode")

# ---------------------------------------------------------------------------
# Extraction destinations
# ---------------------------------------------------------------------------

DESTINATION_BANK = "bank"
DESTINATION_STABLECOINS = "stablecoins"
DESTINATION_TREASURY = "treasury_wallet"

# Default split (fractions, must sum to 1.0)
DEFAULT_SPLIT: Dict[str, float] = {
    DESTINATION_BANK:        0.40,   # 40 %
    DESTINATION_STABLECOINS: 0.35,   # 35 %
    DESTINATION_TREASURY:    0.25,   # 25 %
}

# Minimum pool balance that triggers auto-extraction (USD)
DEFAULT_AUTO_EXTRACT_THRESHOLD_USD: float = 500.0

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExtractionConfig:
    """Configuration for profit extraction destinations and thresholds."""
    # Fraction of each extraction allocated to each destination (must sum to 1.0)
    bank_fraction: float = DEFAULT_SPLIT[DESTINATION_BANK]
    stablecoins_fraction: float = DEFAULT_SPLIT[DESTINATION_STABLECOINS]
    treasury_fraction: float = DEFAULT_SPLIT[DESTINATION_TREASURY]

    # Auto-extraction threshold: extract when pool >= this amount
    auto_extract_threshold_usd: float = DEFAULT_AUTO_EXTRACT_THRESHOLD_USD

    # Minimum individual extraction amount per destination (avoid dust)
    min_extraction_usd: float = 10.0

    # Labels / addresses (informational; used in audit trail)
    bank_label: str = "linked_bank_account"
    stablecoins_label: str = "USDC_on_exchange"
    treasury_label: str = "cold_storage_wallet"

    def validate(self) -> None:
        total = self.bank_fraction + self.stablecoins_fraction + self.treasury_fraction
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Extraction fractions must sum to 1.0, got {total:.4f}"
            )
        for name, val in [
            ("bank_fraction", self.bank_fraction),
            ("stablecoins_fraction", self.stablecoins_fraction),
            ("treasury_fraction", self.treasury_fraction),
        ]:
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be 0–1, got {val}")


@dataclass
class ExtractionRecord:
    """A single completed profit-extraction event."""
    extraction_id: str
    timestamp: str
    total_extracted_usd: float
    bank_usd: float
    stablecoins_usd: float
    treasury_usd: float
    bank_label: str
    stablecoins_label: str
    treasury_label: str
    source_note: str = ""
    pool_before_usd: float = 0.0
    pool_after_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProfitRecord:
    """A single realised-profit log entry."""
    timestamp: str
    symbol: str
    pnl_usd: float
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# ProfitExtractionEngine
# ---------------------------------------------------------------------------


class ProfitExtractionEngine:
    """
    Accumulates realised profits and distributes them to bank,
    stablecoins, and treasury wallet.

    Thread-safe; process-wide singleton via ``get_profit_extraction_engine()``.
    """

    DATA_DIR = Path("data/profit_extraction")

    def __init__(self, config: Optional[ExtractionConfig] = None) -> None:
        self._lock = threading.RLock()
        self._config = config or ExtractionConfig()
        self._config.validate()

        # Pool of profit waiting to be extracted
        self._pool_usd: float = 0.0
        self._total_profit_recorded_usd: float = 0.0
        self._total_extracted_usd: float = 0.0

        # Destination totals
        self._dest_totals: Dict[str, float] = {
            DESTINATION_BANK: 0.0,
            DESTINATION_STABLECOINS: 0.0,
            DESTINATION_TREASURY: 0.0,
        }

        # Audit trails
        self._profit_log: List[ProfitRecord] = []
        self._extraction_log: List[ExtractionRecord] = []

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info(
            "ProfitExtractionEngine initialised | "
            "bank=%.0f%% stablecoins=%.0f%% treasury=%.0f%% | "
            "auto_extract_threshold=$%.2f",
            self._config.bank_fraction * 100,
            self._config.stablecoins_fraction * 100,
            self._config.treasury_fraction * 100,
            self._config.auto_extract_threshold_usd,
        )

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def record_profit(
        self,
        symbol: str,
        pnl_usd: float,
        note: str = "",
        auto_extract: bool = True,
    ) -> float:
        """
        Record a realised profit (or loss) from a closed position.

        Only **positive** P&L is added to the extraction pool.

        Parameters
        ----------
        symbol : str
            The trading symbol that generated the profit.
        pnl_usd : float
            Realised P&L in USD.  Negative values are recorded in the
            profit log but do NOT reduce the extraction pool.
        note : str
            Optional annotation.
        auto_extract : bool
            If True, automatically trigger ``extract()`` when the pool
            exceeds ``config.auto_extract_threshold_usd``.

        Returns
        -------
        float
            Current pool balance after recording.
        """
        with self._lock:
            ts = datetime.now(timezone.utc).isoformat()
            record = ProfitRecord(timestamp=ts, symbol=symbol, pnl_usd=pnl_usd, note=note)
            self._profit_log.append(record)

            if pnl_usd > 0:
                self._pool_usd += pnl_usd
                self._total_profit_recorded_usd += pnl_usd
                logger.info(
                    "💰 Profit recorded: $%.2f from %s | pool=$%.2f",
                    pnl_usd, symbol, self._pool_usd,
                )

                # Also notify PortfolioProfitEngine if available
                if _PPE_AVAILABLE and get_portfolio_profit_engine is not None:
                    try:
                        ppe = get_portfolio_profit_engine()
                        ppe.record_trade(symbol=symbol, pnl_usd=pnl_usd, is_win=True)
                    except Exception as exc:
                        logger.warning("PortfolioProfitEngine.record_trade failed: %s", exc)
            else:
                logger.debug(
                    "Loss/zero recorded: $%.2f from %s (not added to pool)",
                    pnl_usd, symbol,
                )

            pool = self._pool_usd
            self._save_state()

        # Auto-extract outside the lock to avoid nested lock issues
        if auto_extract and pool >= self._config.auto_extract_threshold_usd:
            logger.info(
                "Auto-extraction triggered (pool=$%.2f >= threshold=$%.2f)",
                pool, self._config.auto_extract_threshold_usd,
            )
            self.extract(note=f"auto-extract triggered by {symbol} profit")

        return self._pool_usd

    def extract(
        self,
        amount_usd: Optional[float] = None,
        note: str = "",
    ) -> Optional[ExtractionRecord]:
        """
        Extract profits from the pool and distribute to destinations.

        Parameters
        ----------
        amount_usd : float, optional
            Amount to extract.  If None, extracts the entire pool balance.
        note : str
            Optional annotation stored in the extraction log.

        Returns
        -------
        ExtractionRecord or None
            The extraction record, or None if nothing was extracted (e.g.
            pool empty or amounts below minimum threshold).
        """
        with self._lock:
            if self._pool_usd <= 0:
                logger.warning("extract() called but pool is empty")
                return None

            extractable = amount_usd if amount_usd is not None else self._pool_usd
            extractable = min(extractable, self._pool_usd)

            if extractable < self._config.min_extraction_usd:
                logger.warning(
                    "Extractable amount $%.2f below minimum $%.2f — skipping",
                    extractable, self._config.min_extraction_usd,
                )
                return None

            cfg = self._config
            bank_usd = extractable * cfg.bank_fraction
            stable_usd = extractable * cfg.stablecoins_fraction
            treasury_usd = extractable * cfg.treasury_fraction

            # Correct for floating-point rounding
            allocated = bank_usd + stable_usd + treasury_usd
            treasury_usd += extractable - allocated  # absorb rounding in treasury

            pool_before = self._pool_usd
            self._pool_usd -= extractable
            self._pool_usd = max(0.0, self._pool_usd)

            self._total_extracted_usd += extractable
            self._dest_totals[DESTINATION_BANK] += bank_usd
            self._dest_totals[DESTINATION_STABLECOINS] += stable_usd
            self._dest_totals[DESTINATION_TREASURY] += treasury_usd

            import uuid
            rec = ExtractionRecord(
                extraction_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                total_extracted_usd=extractable,
                bank_usd=bank_usd,
                stablecoins_usd=stable_usd,
                treasury_usd=treasury_usd,
                bank_label=cfg.bank_label,
                stablecoins_label=cfg.stablecoins_label,
                treasury_label=cfg.treasury_label,
                source_note=note,
                pool_before_usd=pool_before,
                pool_after_usd=self._pool_usd,
            )
            self._extraction_log.append(rec)
            self._save_state()

            logger.info(
                "🏦 Profit extracted: $%.2f total | "
                "bank=$%.2f  stablecoins=$%.2f  treasury=$%.2f | "
                "pool=$%.2f → $%.2f",
                extractable,
                bank_usd, stable_usd, treasury_usd,
                pool_before, self._pool_usd,
            )

            # Dispatch to real destinations (stubs — replace with live integrations)
            self._send_to_bank(bank_usd, cfg.bank_label)
            self._send_to_stablecoins(stable_usd, cfg.stablecoins_label)
            self._send_to_treasury(treasury_usd, cfg.treasury_label)

            return rec

    # ------------------------------------------------------------------
    # Destination dispatch stubs
    # ------------------------------------------------------------------

    def _send_to_bank(self, amount_usd: float, label: str) -> None:
        """
        Initiate a fiat bank transfer.

        **Replace this stub** with a real bank-transfer API call
        (e.g. Plaid, Stripe, Coinbase withdrawal API, or a wire-transfer
        integration with your custodian).
        """
        if amount_usd < self._config.min_extraction_usd:
            logger.debug("Bank transfer skipped — amount $%.2f below minimum", amount_usd)
            return
        logger.info(
            "🏛️  [BANK TRANSFER] $%.2f → %s  "
            "(TODO: wire up bank-transfer API)",
            amount_usd, label,
        )

    def _send_to_stablecoins(self, amount_usd: float, label: str) -> None:
        """
        Convert profits to stablecoins (USDC/USDT).

        **Replace this stub** with a real on-exchange conversion order
        or an on-chain transfer via Web3 / Coinbase Commerce.
        """
        if amount_usd < self._config.min_extraction_usd:
            logger.debug("Stablecoin conversion skipped — amount $%.2f below minimum", amount_usd)
            return
        logger.info(
            "🪙  [STABLECOIN] $%.2f → %s  "
            "(TODO: wire up stablecoin conversion / on-chain transfer)",
            amount_usd, label,
        )

    def _send_to_treasury(self, amount_usd: float, label: str) -> None:
        """
        Transfer profits to the treasury / cold-storage wallet.

        **Replace this stub** with a real wallet-transfer API call
        (e.g. Coinbase Prime, Fireblocks, or on-chain send).
        """
        if amount_usd < self._config.min_extraction_usd:
            logger.debug("Treasury transfer skipped — amount $%.2f below minimum", amount_usd)
            return
        logger.info(
            "🔐  [TREASURY] $%.2f → %s  "
            "(TODO: wire up cold-storage / treasury wallet transfer)",
            amount_usd, label,
        )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return self.DATA_DIR / "state.json"

    def _save_state(self) -> None:
        try:
            state = {
                "pool_usd": self._pool_usd,
                "total_profit_recorded_usd": self._total_profit_recorded_usd,
                "total_extracted_usd": self._total_extracted_usd,
                "dest_totals": self._dest_totals,
                "profit_log": [r.to_dict() for r in self._profit_log[-500:]],
                "extraction_log": [r.to_dict() for r in self._extraction_log[-200:]],
            }
            tmp = self._state_path().with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            tmp.replace(self._state_path())
        except Exception as exc:
            logger.warning("Failed to save state: %s", exc)

    def _load_state(self) -> None:
        path = self._state_path()
        if not path.exists():
            return
        try:
            with open(path) as f:
                state = json.load(f)
            self._pool_usd = float(state.get("pool_usd", 0.0))
            self._total_profit_recorded_usd = float(state.get("total_profit_recorded_usd", 0.0))
            self._total_extracted_usd = float(state.get("total_extracted_usd", 0.0))
            self._dest_totals = state.get("dest_totals", dict(self._dest_totals))
            self._profit_log = [
                ProfitRecord(**r) for r in state.get("profit_log", [])
            ]
            self._extraction_log = [
                ExtractionRecord(**r) for r in state.get("extraction_log", [])
            ]
            logger.info(
                "State loaded | pool=$%.2f  total_extracted=$%.2f",
                self._pool_usd, self._total_extracted_usd,
            )
        except Exception as exc:
            logger.warning("Failed to load state (starting fresh): %s", exc)

    # ------------------------------------------------------------------
    # Status & reporting
    # ------------------------------------------------------------------

    def get_pool_balance(self) -> float:
        """Return the current unextracted profit pool balance."""
        with self._lock:
            return self._pool_usd

    def get_destination_totals(self) -> Dict[str, float]:
        """Return cumulative amounts sent to each destination."""
        with self._lock:
            return dict(self._dest_totals)

    def get_recent_extractions(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return the *n* most recent extraction records."""
        with self._lock:
            return [r.to_dict() for r in self._extraction_log[-n:]]

    def get_report(self) -> str:
        """Generate a human-readable profit extraction report."""
        with self._lock:
            cfg = self._config
            lines = [
                "=" * 70,
                "  NIJA PROFIT EXTRACTION ENGINE — STATUS REPORT",
                "=" * 70,
                f"  Pool Balance         : ${self._pool_usd:>14,.2f}",
                f"  Total Profit Recorded: ${self._total_profit_recorded_usd:>14,.2f}",
                f"  Total Extracted      : ${self._total_extracted_usd:>14,.2f}",
                f"  Extractions Count    : {len(self._extraction_log):>14,}",
                "",
                "  DESTINATION BREAKDOWN",
                "-" * 70,
                f"  {'Destination':<25} {'Split':>7}  {'Total Sent':>14}  {'Label'}",
                "-" * 70,
                f"  {'Bank':<25} {cfg.bank_fraction*100:>6.0f}%  "
                f"${self._dest_totals[DESTINATION_BANK]:>13,.2f}  {cfg.bank_label}",
                f"  {'Stablecoins':<25} {cfg.stablecoins_fraction*100:>6.0f}%  "
                f"${self._dest_totals[DESTINATION_STABLECOINS]:>13,.2f}  {cfg.stablecoins_label}",
                f"  {'Treasury Wallet':<25} {cfg.treasury_fraction*100:>6.0f}%  "
                f"${self._dest_totals[DESTINATION_TREASURY]:>13,.2f}  {cfg.treasury_label}",
                "-" * 70,
                f"  Auto-Extract Threshold: ${cfg.auto_extract_threshold_usd:,.2f}",
            ]

            if self._extraction_log:
                last = self._extraction_log[-1]
                lines += [
                    "",
                    "  LAST EXTRACTION",
                    f"  Timestamp : {last.timestamp}",
                    f"  Total     : ${last.total_extracted_usd:,.2f}",
                    f"  Bank      : ${last.bank_usd:,.2f}",
                    f"  Stablecoins: ${last.stablecoins_usd:,.2f}",
                    f"  Treasury  : ${last.treasury_usd:,.2f}",
                ]

            lines.append("=" * 70)
            return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ProfitExtractionEngine] = None
_instance_lock = threading.Lock()


def get_profit_extraction_engine(
    config: Optional[ExtractionConfig] = None,
) -> ProfitExtractionEngine:
    """
    Return the process-wide :class:`ProfitExtractionEngine` singleton.

    The *config* parameter is only applied on **first call**.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ProfitExtractionEngine(config=config)
    return _instance


__all__ = [
    "DESTINATION_BANK",
    "DESTINATION_STABLECOINS",
    "DESTINATION_TREASURY",
    "DEFAULT_SPLIT",
    "ExtractionConfig",
    "ExtractionRecord",
    "ProfitRecord",
    "ProfitExtractionEngine",
    "get_profit_extraction_engine",
]

# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    # Use a low threshold so the demo triggers an auto-extraction
    cfg = ExtractionConfig(auto_extract_threshold_usd=100.0)
    engine = get_profit_extraction_engine(config=cfg)

    print(engine.get_report())

    # Simulate a few winning trades
    engine.record_profit("BTC-USD", pnl_usd=75.0, note="APEX scalp")
    engine.record_profit("ETH-USD", pnl_usd=60.0, note="APEX scalp")   # triggers auto-extract

    print("\nAfter auto-extraction:")
    print(engine.get_report())
