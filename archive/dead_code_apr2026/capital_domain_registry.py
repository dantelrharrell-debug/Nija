"""
NIJA Capital Domain Registry
==============================
Hard capital namespace isolation — prevents cross-broker contamination.

Problem solved
--------------
Without this module the system operates on a single shared ``total_capital``
figure (Kraken + Coinbase summed).  When Kraken is offline and only Coinbase
($5.43) is connected, the global capital becomes $5.43 and everything breaks:

  * AI hub thinks the portfolio is worth $5.43 → sizes become 0
  * Portfolio intelligence triggers "undercapitalized" and vetoes all trades
  * MIN_DEPLOYABLE_BALANCE=$25 marks Coinbase PASSIVE immediately
  * FATAL: Capital below minimum — trading disabled ($5.43 < $25.00)

Solution
--------
Each broker is its own capital *domain* with independent rules, state and
risk limits.  Domains are **strictly isolated** by default:

  * ``coinbase_nano``    — local scope: $5 → $50 CAPITAL_BUILD mode
  * ``kraken_primary``  — authoritative execution capital
  * ``platform_global`` — read-only aggregation (no trading)

No balance from an isolated domain can influence any other domain's sizing,
minimum checks, or AI capital calculations.  The only sanctioned way to move
capital between domains is the explicit, audited :meth:`transfer` method.

Usage
-----
::

    from bot.capital_domain_registry import get_capital_domain_registry

    reg = get_capital_domain_registry()

    # Update balances after each broker refresh
    reg.update_balance("coinbase_nano",   5.43)
    reg.update_balance("kraken_primary", 1_240.00)

    # Check before opening a trade (domain-local rules only)
    ok, reason = reg.can_open("coinbase_nano", "BTC-USD", risk_usd=0.05)

    # Record opened position
    reg.record_opened("coinbase_nano", "BTC-USD", size_usd=2.50)

    # Read effective (non-NANO) capital for global decisions
    global_capital = reg.authoritative_capital()   # → 1_240.00  (Coinbase excluded)

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.capital_domains")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOMAIN_COINBASE_NANO   = "coinbase_nano"
DOMAIN_KRAKEN_PRIMARY  = "kraken_primary"
DOMAIN_PLATFORM_GLOBAL = "platform_global"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CapitalDomainConfig:
    """
    Static configuration for a single capital domain.

    All values are **per-domain** — they apply only to trades executed
    within this domain and have zero effect on any other domain.
    """
    domain_id: str
    broker: str
    description: str

    # Position rules
    max_positions: int = 5
    max_risk_per_trade_pct: float = 0.02          # e.g. 0.02 = 2%
    max_portfolio_heat_pct: float = 0.60          # max total open / balance

    # Trade size rules
    min_trade_usd: float = 2.0                    # Never go below this
    max_trade_usd: float = 10_000.0               # Never go above this

    # Mode constraints
    allowed_modes: frozenset = field(default_factory=frozenset)   # empty = all modes
    trade_mode: str = "STANDARD"                  # e.g. "CAPITAL_BUILD", "STANDARD"

    # Safety
    absolute_min_capital_usd: float = 5.0         # Hard floor; trading stops below this
    isolate: bool = True                          # False = aggregation domain (read-only)


@dataclass
class DomainState:
    """
    Mutable live state for a single capital domain.

    Access is always via the :class:`CapitalDomainRegistry` which holds
    the lock, so callers must never mutate this directly.
    """
    domain_id: str
    balance: float = 0.0
    open_positions: Dict[str, float] = field(default_factory=dict)   # symbol → size_usd
    realized_pnl: float = 0.0
    trade_count: int = 0
    last_updated: Optional[datetime] = None

    @property
    def total_open_usd(self) -> float:
        return sum(self.open_positions.values())

    @property
    def open_count(self) -> int:
        return len(self.open_positions)

    @property
    def locked(self) -> bool:
        """True when balance is below absolute_min_capital_usd — checked by registry."""
        return False  # Registry evaluates against config threshold


@dataclass
class DomainTransferRecord:
    """Audit record for an explicit capital transfer between domains."""
    from_domain: str
    to_domain: str
    amount_usd: float
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Pre-configured domain definitions
# ---------------------------------------------------------------------------

CAPITAL_DOMAINS: Dict[str, CapitalDomainConfig] = {
    DOMAIN_COINBASE_NANO: CapitalDomainConfig(
        domain_id=DOMAIN_COINBASE_NANO,
        broker="coinbase",
        description=(
            "Coinbase micro-account — CAPITAL_BUILD mode ($0–$50). "
            "Isolated: cannot block startup, cannot influence global AI capital."
        ),
        max_positions=1,
        # 0.5% risk per trade — matches position_manager.py NANO_PLATFORM tier table.
        # NOTE: For a $5 account, 0.5% risk = $0.025 max loss.  The min_trade_usd
        # ($2) represents 40% of a $5 balance — that tension is intentional: the
        # risk_pct cap governs stop-loss sizing while min_trade_usd is the exchange
        # floor.  The position manager's fee viability gate (Gate 8) is the real
        # safeguard against trades that cannot overcome fees.
        max_risk_per_trade_pct=0.005,   # 0.5% — consistent with position_manager NANO_PLATFORM
        max_portfolio_heat_pct=0.50,
        min_trade_usd=2.0,              # fee-adjusted minimum
        max_trade_usd=25.0,             # never risk more than ~50% of a $50 account
        allowed_modes=frozenset({"SCALP", "HIGH_CONFIDENCE_ONLY"}),
        trade_mode="CAPITAL_BUILD",
        absolute_min_capital_usd=5.0,   # below $5 execution is unreliable
        isolate=True,
    ),
    DOMAIN_KRAKEN_PRIMARY: CapitalDomainConfig(
        domain_id=DOMAIN_KRAKEN_PRIMARY,
        broker="kraken",
        description=(
            "Kraken primary execution capital — authoritative source of truth. "
            "Gates system startup. All standard modes permitted. "
            "isolate=False so authoritative_capital() always includes Kraken."
        ),
        max_positions=5,
        max_risk_per_trade_pct=0.020,   # 2%
        max_portfolio_heat_pct=0.60,
        min_trade_usd=10.0,
        max_trade_usd=50_000.0,
        allowed_modes=frozenset(),       # empty = all modes allowed
        trade_mode="STANDARD",
        absolute_min_capital_usd=25.0,
        isolate=False,                  # AUTHORITATIVE — always counted in authoritative_capital()
    ),
    DOMAIN_PLATFORM_GLOBAL: CapitalDomainConfig(
        domain_id=DOMAIN_PLATFORM_GLOBAL,
        broker="platform",
        description=(
            "Platform-level capital view — read-only aggregation of all domains. "
            "Not a trading domain; used for reporting only."
        ),
        max_positions=0,                # no direct trading
        max_risk_per_trade_pct=0.0,
        max_portfolio_heat_pct=1.0,
        min_trade_usd=0.0,
        max_trade_usd=0.0,
        allowed_modes=frozenset(),
        trade_mode="AGGREGATE",
        absolute_min_capital_usd=0.0,
        isolate=False,                  # aggregation domain — read-only
    ),
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class CapitalDomainRegistry:
    """
    Process-wide registry of isolated capital domains.

    Each domain is a completely independent risk engine.  Callers obtain
    the singleton via :func:`get_capital_domain_registry`.

    Key invariants
    ~~~~~~~~~~~~~~
    1. ``can_open()`` checks ONLY the target domain's own balance and open
       positions.  Another domain's balance can never affect this result.
    2. ``authoritative_capital()`` returns the sum of non-isolated domains
       (Kraken).  The AI hub and global minimum check should use this.
    3. Capital moves between domains **only** through :meth:`transfer`,
       which creates an audited :class:`DomainTransferRecord`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._configs: Dict[str, CapitalDomainConfig] = {}
        self._states: Dict[str, DomainState] = {}
        self._transfers: List[DomainTransferRecord] = []

        # Pre-register all built-in domains
        for cfg in CAPITAL_DOMAINS.values():
            self._register_locked(cfg)

    # ------------------------------------------------------------------
    # Domain registration
    # ------------------------------------------------------------------

    def register_domain(self, config: CapitalDomainConfig) -> None:
        """Register (or replace) a domain configuration."""
        with self._lock:
            self._register_locked(config)

    def _register_locked(self, config: CapitalDomainConfig) -> None:
        self._configs[config.domain_id] = config
        if config.domain_id not in self._states:
            self._states[config.domain_id] = DomainState(domain_id=config.domain_id)
        logger.info(
            "[CapitalDomains] registered domain '%s' broker=%s isolate=%s",
            config.domain_id, config.broker, config.isolate,
        )

    # ------------------------------------------------------------------
    # Balance management
    # ------------------------------------------------------------------

    def update_balance(self, domain_id: str, balance: float) -> None:
        """
        Set the current USD balance for a domain.

        Call once per cycle after each broker refresh so the domain's risk
        checks always operate on the latest observed figure.
        """
        if domain_id not in self._configs:
            logger.warning(
                "[CapitalDomains] update_balance: unknown domain '%s' — skipped",
                domain_id,
            )
            return
        balance = max(0.0, float(balance))
        with self._lock:
            self._states[domain_id].balance = balance
            self._states[domain_id].last_updated = datetime.now(timezone.utc)
        logger.debug(
            "[CapitalDomains] domain='%s' balance updated to $%.2f",
            domain_id, balance,
        )

    def get_balance(self, domain_id: str) -> float:
        """Return the last-known balance for a domain (0.0 if unknown)."""
        with self._lock:
            state = self._states.get(domain_id)
            return state.balance if state else 0.0

    # ------------------------------------------------------------------
    # Trade gate
    # ------------------------------------------------------------------

    def can_open(
        self,
        domain_id: str,
        symbol: str,
        risk_usd: float = 0.0,
        trade_mode: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Check whether a new position is allowed within *domain_id*.

        All checks are **strictly domain-local** — no other domain's state
        is consulted.

        Returns
        -------
        (True, "")
            Trade is permitted.
        (False, reason_string)
            Trade is blocked; *reason_string* describes why.
        """
        with self._lock:
            cfg = self._configs.get(domain_id)
            state = self._states.get(domain_id)

        if cfg is None or state is None:
            return False, f"Unknown domain '{domain_id}'"

        if not cfg.isolate and cfg.trade_mode == "AGGREGATE":
            return False, f"Domain '{domain_id}' is aggregation-only (no trading)"

        # Hard capital floor
        if state.balance < cfg.absolute_min_capital_usd:
            return (
                False,
                f"[{domain_id}] Balance ${state.balance:.2f} < "
                f"absolute_min ${cfg.absolute_min_capital_usd:.2f} — trading unsafe",
            )

        # Mode constraint
        if trade_mode and cfg.allowed_modes and trade_mode not in cfg.allowed_modes:
            return (
                False,
                f"[{domain_id}] Mode '{trade_mode}' not allowed "
                f"(allowed: {sorted(cfg.allowed_modes)}, mode='{cfg.trade_mode}')",
            )

        # Position cap
        if symbol not in state.open_positions and state.open_count >= cfg.max_positions:
            return (
                False,
                f"[{domain_id}] Position cap {state.open_count}/{cfg.max_positions} reached",
            )

        # Portfolio heat
        if state.balance > 0:
            heat = state.total_open_usd / state.balance
            if heat >= cfg.max_portfolio_heat_pct:
                return (
                    False,
                    f"[{domain_id}] Portfolio heat {heat*100:.1f}% >= "
                    f"{cfg.max_portfolio_heat_pct*100:.0f}%",
                )

        # Risk-per-trade
        if risk_usd > 0 and state.balance > 0:
            risk_pct = risk_usd / state.balance
            if risk_pct > cfg.max_risk_per_trade_pct:
                return (
                    False,
                    f"[{domain_id}] Risk ${risk_usd:.2f} "
                    f"({risk_pct*100:.2f}%) > max {cfg.max_risk_per_trade_pct*100:.1f}%",
                )

        return True, ""

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def record_opened(
        self,
        domain_id: str,
        symbol: str,
        size_usd: float,
    ) -> None:
        """Record a newly opened position in the domain's local state."""
        with self._lock:
            state = self._states.get(domain_id)
            if state is None:
                logger.warning("[CapitalDomains] record_opened: unknown domain '%s'", domain_id)
                return
            state.open_positions[symbol] = (
                state.open_positions.get(symbol, 0.0) + size_usd
            )
            state.trade_count += 1
        logger.info(
            "[CapitalDomains] domain='%s' opened %s $%.2f (total_open=$%.2f)",
            domain_id, symbol, size_usd,
            self._states[domain_id].total_open_usd,
        )

    def record_closed(
        self,
        domain_id: str,
        symbol: str,
        pnl_usd: float = 0.0,
    ) -> None:
        """Record a closed position and accumulate PnL."""
        with self._lock:
            state = self._states.get(domain_id)
            if state is None:
                logger.warning("[CapitalDomains] record_closed: unknown domain '%s'", domain_id)
                return
            state.open_positions.pop(symbol, None)
            state.realized_pnl += pnl_usd
        logger.info(
            "[CapitalDomains] domain='%s' closed %s pnl=$%.2f",
            domain_id, symbol, pnl_usd,
        )

    # ------------------------------------------------------------------
    # Capital aggregation (explicit opt-in only)
    # ------------------------------------------------------------------

    def authoritative_capital(self) -> float:
        """
        Sum of balances from **non-isolated, non-aggregate** trading domains.

        ``isolate=False`` is the signal that a domain is authoritative (e.g.
        Kraken).  Domains with ``isolate=True`` (Coinbase NANO) and
        ``trade_mode="AGGREGATE"`` (platform_global read-only view) are both
        excluded.

        Use this for:
          • Global minimum checks
          • AI hub ``portfolio_value``
          • Portfolio intelligence ``effective_capital``

        Coinbase NANO (``isolate=True``) is intentionally excluded so a $5
        sandbox balance can never make the system appear globally underfunded.
        """
        with self._lock:
            total = 0.0
            for domain_id, cfg in self._configs.items():
                if cfg.isolate:
                    continue                    # NANO / sandbox domains — excluded
                if cfg.trade_mode == "AGGREGATE":
                    continue                    # read-only aggregation domains — excluded
                state = self._states[domain_id]
                total += state.balance
            return total

    def aggregate_balances(self, *domain_ids: str) -> float:
        """
        Explicit opt-in balance aggregation across named domains.

        This is the ONLY way to combine balances from multiple domains.
        Returns the sum of the named domains' balances (read-only).
        """
        with self._lock:
            return sum(
                self._states[did].balance
                for did in domain_ids
                if did in self._states
            )

    # ------------------------------------------------------------------
    # Audited transfer
    # ------------------------------------------------------------------

    def transfer(
        self,
        from_domain: str,
        to_domain: str,
        amount_usd: float,
        reason: str = "",
    ) -> bool:
        """
        Move capital from one domain to another — the ONLY sanctioned
        way to cross domain boundaries.

        Returns ``True`` on success, ``False`` if the source domain has
        insufficient balance or either domain is unknown.
        """
        with self._lock:
            src = self._states.get(from_domain)
            dst = self._states.get(to_domain)
            if src is None or dst is None:
                logger.error(
                    "[CapitalDomains] transfer failed: unknown domain(s) %s → %s",
                    from_domain, to_domain,
                )
                return False
            if src.balance < amount_usd:
                logger.error(
                    "[CapitalDomains] transfer failed: %s balance $%.2f < transfer $%.2f",
                    from_domain, src.balance, amount_usd,
                )
                return False
            src.balance -= amount_usd
            dst.balance += amount_usd
            record = DomainTransferRecord(
                from_domain=from_domain,
                to_domain=to_domain,
                amount_usd=amount_usd,
                reason=reason,
            )
            self._transfers.append(record)
        logger.info(
            "[CapitalDomains] transfer $%.2f: %s → %s | reason=%s",
            amount_usd, from_domain, to_domain, reason or "(none)",
        )
        return True

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_domain_state(self, domain_id: str) -> Optional[DomainState]:
        """Return a copy of the current state for a domain (or None)."""
        with self._lock:
            state = self._states.get(domain_id)
            if state is None:
                return None
            # Return a shallow copy so callers cannot mutate registry state
            return DomainState(
                domain_id=state.domain_id,
                balance=state.balance,
                open_positions=dict(state.open_positions),
                realized_pnl=state.realized_pnl,
                trade_count=state.trade_count,
                last_updated=state.last_updated,
            )

    def get_full_report(self) -> Dict:
        """Full diagnostic snapshot of all domains and the transfer log."""
        with self._lock:
            return {
                "authoritative_capital": self.authoritative_capital(),
                "domains": {
                    did: {
                        "balance":          state.balance,
                        "open_positions":   dict(state.open_positions),
                        "total_open_usd":   state.total_open_usd,
                        "realized_pnl":     state.realized_pnl,
                        "trade_count":      state.trade_count,
                        "isolate":          self._configs[did].isolate,
                        "trade_mode":       self._configs[did].trade_mode,
                        "min_capital":      self._configs[did].absolute_min_capital_usd,
                        "last_updated":     state.last_updated.isoformat()
                                            if state.last_updated else None,
                    }
                    for did, state in self._states.items()
                },
                "transfer_log": [
                    {
                        "from":   r.from_domain,
                        "to":     r.to_domain,
                        "amount": r.amount_usd,
                        "reason": r.reason,
                        "time":   r.timestamp.isoformat(),
                    }
                    for r in self._transfers[-20:]   # last 20 transfers
                ],
            }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_REGISTRY: Optional[CapitalDomainRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_capital_domain_registry() -> CapitalDomainRegistry:
    """Return the process-wide :class:`CapitalDomainRegistry` singleton."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = CapitalDomainRegistry()
            logger.info(
                "[CapitalDomains] registry created with %d pre-configured domains",
                len(CAPITAL_DOMAINS),
            )
    return _REGISTRY
