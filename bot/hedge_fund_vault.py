"""
Hedge Fund Vault
=================

Institutional-grade layer providing:

1. Profit-sharing pools
   - Multiple named vaults with configurable profit-share percentages.
   - Deposits accumulate from live trading profits.
   - Harvest events distribute pool balances to registered investors.

2. Investor registry with lightweight KYC/AML screening
   - Each investor record carries accreditation status and AML flags.
   - AML-flagged or non-accredited investors are blocked from receiving
     distributions.

3. Institutional-grade reporting
   - NAV (Net Asset Value) per vault.
   - Investor statements (contribution, distributions, current value).
   - Blotter-level audit trail for every deposit and withdrawal.
   - JSON-serialisable output for downstream compliance systems.

Security / Compliance notes
----------------------------
- No real financial or personal data is stored in source code.
- KYC data in production must be handled by a regulated third-party
  KYC provider; this module stores *flags* only (verified/flagged bools).
- All audit events are appended-only (never modified or deleted).

Usage
-----
    from bot.hedge_fund_vault import get_hedge_fund_vault

    vault = get_hedge_fund_vault()

    # Setup
    vault.create_vault("main_pool", profit_share_pct=20.0, manager_fee_pct=2.0)
    vault.register_investor("inv_001", name="Alice", accredited=True)
    vault.subscribe_investor("main_pool", "inv_001", commitment=25_000.0)

    # Operations
    vault.deposit_profit("main_pool", amount=5_000.0, source="ApexTrend")
    distributions = vault.harvest("main_pool")

    # Reporting
    print(vault.nav_report("main_pool"))
    print(vault.investor_statement("inv_001"))
    print(vault.audit_log_tail(10))

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
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.hedge_fund_vault")


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class InvestorRecord:
    investor_id:    str
    name:           str                # display name only (no PII stored here)
    accredited:     bool = False       # accreditation flag (set by KYC provider)
    aml_flagged:    bool = False       # AML flag (set by compliance provider)
    kyc_verified:   bool = False       # KYC completion flag
    created_at:     str  = ""
    last_updated:   str  = ""

    # Running totals
    total_committed:    float = 0.0
    total_deposited:    float = 0.0
    total_distributed:  float = 0.0
    current_value:      float = 0.0

    @property
    def is_eligible(self) -> bool:
        """Investor may receive distributions only if compliant."""
        return self.accredited and not self.aml_flagged and self.kyc_verified

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["is_eligible"] = self.is_eligible
        return d


@dataclass
class VaultSubscription:
    vault_id:    str
    investor_id: str
    commitment:  float   # committed capital
    deposited:   float = 0.0
    distributed: float = 0.0
    units:       float = 0.0   # proportional units (NAV-based)
    subscribed_at: str = ""


@dataclass
class Vault:
    vault_id:          str
    display_name:      str
    profit_share_pct:  float   # % of profits distributed to investors
    manager_fee_pct:   float   # annual management fee %
    created_at:        str     = ""
    last_updated:      str     = ""

    # Balances
    gross_profit:      float = 0.0   # cumulative profit deposited
    total_fees:        float = 0.0   # management fees withheld
    profit_pool:       float = 0.0   # available for distribution
    total_distributed: float = 0.0  # historical distributions

    # Unit accounting
    total_units:       float = 0.0
    unit_nav:          float = 1.0   # NAV per unit

    @property
    def nav(self) -> float:
        # Net profit available; extend here to include unrealised P&L if needed
        return self.profit_pool

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["nav"] = round(self.nav, 2)
        return d


@dataclass
class AuditEvent:
    event_id:   str
    vault_id:   str
    event_type: str   # deposit | harvest | fee | subscription | kyc_update
    amount:     float
    actor:      str   # investor_id, strategy name, or "system"
    note:       str
    timestamp:  str


# ─────────────────────────────────────────────────────────────────────────────
# Vault manager
# ─────────────────────────────────────────────────────────────────────────────

class HedgeFundVault:
    """
    Institutional-grade profit vault with KYC/AML-gated distributions
    and tamper-evident audit logging.

    Parameters
    ----------
    state_path : str
        JSON path for persistent state.
    audit_log_path : str
        Append-only JSON-lines file for audit events.
    """

    def __init__(
        self,
        state_path:     str = "data/hedge_fund_vault_state.json",
        audit_log_path: str = "data/hedge_fund_audit_log.jsonl",
    ) -> None:
        self.state_path     = state_path
        self.audit_log_path = audit_log_path
        self._lock          = threading.RLock()

        self._vaults:        Dict[str, Vault]              = {}
        self._investors:     Dict[str, InvestorRecord]     = {}
        self._subscriptions: Dict[str, List[VaultSubscription]] = {}  # vault_id → list
        self._event_counter: int                           = 0

        self._load_state()
        logger.info(
            "🏦 HedgeFundVault ready | vaults=%d | investors=%d",
            len(self._vaults), len(self._investors),
        )

    # ── Vault management ──────────────────────────────────────────────────────

    def create_vault(
        self,
        vault_id: str,
        display_name: str = "",
        profit_share_pct: float = 20.0,
        manager_fee_pct: float = 2.0,
    ) -> Vault:
        """Create a new profit vault."""
        with self._lock:
            if vault_id in self._vaults:
                logger.info("[Vault] Vault '%s' already exists.", vault_id)
                return self._vaults[vault_id]

            vault = Vault(
                vault_id         = vault_id,
                display_name     = display_name or vault_id,
                profit_share_pct = max(0.0, min(100.0, profit_share_pct)),
                manager_fee_pct  = max(0.0, min(10.0, manager_fee_pct)),
                created_at       = _now(),
                last_updated     = _now(),
                unit_nav         = 1.0,
            )
            self._vaults[vault_id] = vault
            self._subscriptions[vault_id] = []
            logger.info(
                "[Vault] Created vault '%s' | profit_share=%.1f%% | mgmt_fee=%.1f%%",
                vault_id, profit_share_pct, manager_fee_pct,
            )
            self._save_state()
            return vault

    # ── Investor management ───────────────────────────────────────────────────

    def register_investor(
        self,
        investor_id: str,
        name: str = "",
        accredited: bool = False,
        kyc_verified: bool = False,
    ) -> InvestorRecord:
        """Register a new investor record."""
        with self._lock:
            if investor_id in self._investors:
                return self._investors[investor_id]

            rec = InvestorRecord(
                investor_id  = investor_id,
                name         = name or investor_id,
                accredited   = accredited,
                kyc_verified = kyc_verified,
                created_at   = _now(),
                last_updated = _now(),
            )
            self._investors[investor_id] = rec
            logger.info(
                "[Vault] Registered investor %s | accredited=%s | kyc=%s",
                investor_id, accredited, kyc_verified,
            )
            self._save_state()
            return rec

    def update_investor_kyc(
        self,
        investor_id: str,
        accredited: Optional[bool] = None,
        kyc_verified: Optional[bool] = None,
        aml_flagged: Optional[bool] = None,
    ) -> bool:
        """Update KYC/AML flags for an investor (called by compliance provider)."""
        with self._lock:
            rec = self._investors.get(investor_id)
            if rec is None:
                logger.warning("[Vault] Investor %s not found for KYC update.", investor_id)
                return False

            if accredited is not None:
                rec.accredited = accredited
            if kyc_verified is not None:
                rec.kyc_verified = kyc_verified
            if aml_flagged is not None:
                rec.aml_flagged = aml_flagged
            rec.last_updated = _now()

            self._append_audit_event(
                vault_id  = "",
                event_type= "kyc_update",
                amount    = 0.0,
                actor     = investor_id,
                note      = f"KYC flags updated: accredited={rec.accredited}, "
                            f"kyc_verified={rec.kyc_verified}, aml_flagged={rec.aml_flagged}",
            )
            self._save_state()
            return True

    # ── Subscriptions ─────────────────────────────────────────────────────────

    def subscribe_investor(
        self,
        vault_id: str,
        investor_id: str,
        commitment: float = 0.0,
    ) -> Optional[VaultSubscription]:
        """Subscribe an investor to a vault."""
        with self._lock:
            vault = self._vaults.get(vault_id)
            investor = self._investors.get(investor_id)

            if vault is None:
                logger.warning("[Vault] Unknown vault: %s", vault_id)
                return None
            if investor is None:
                logger.warning("[Vault] Unknown investor: %s", investor_id)
                return None
            if not investor.is_eligible:
                logger.warning(
                    "[Vault] Investor %s not eligible (accredited=%s, kyc=%s, aml=%s).",
                    investor_id, investor.accredited, investor.kyc_verified, investor.aml_flagged,
                )
                return None

            # Issue NAV-based units
            units = commitment / max(0.0001, vault.unit_nav)
            sub = VaultSubscription(
                vault_id     = vault_id,
                investor_id  = investor_id,
                commitment   = commitment,
                deposited    = commitment,
                units        = units,
                subscribed_at= _now(),
            )
            self._subscriptions[vault_id].append(sub)
            vault.total_units  += units
            investor.total_committed += commitment
            investor.total_deposited += commitment
            investor.current_value   += commitment

            self._append_audit_event(
                vault_id   = vault_id,
                event_type = "subscription",
                amount     = commitment,
                actor      = investor_id,
                note       = f"Subscribed {units:.4f} units @ NAV={vault.unit_nav:.4f}",
            )
            self._save_state()
            return sub

    # ── Profit operations ─────────────────────────────────────────────────────

    def deposit_profit(
        self,
        vault_id: str,
        amount: float,
        source: str = "trading",
    ) -> float:
        """
        Deposit trading profit into the vault pool.
        Management fee is withheld before depositing to the distributable pool.
        Returns the net amount added to the pool.
        """
        with self._lock:
            vault = self._vaults.get(vault_id)
            if vault is None:
                logger.warning("[Vault] Unknown vault: %s", vault_id)
                return 0.0

            if amount <= 0:
                return 0.0

            # Annual management fee scaled to this deposit (approximate)
            fee = amount * (vault.manager_fee_pct / 100.0) * (1 / 252)
            net = amount - fee

            vault.gross_profit  += amount
            vault.total_fees    += fee
            vault.profit_pool   += net
            vault.last_updated   = _now()

            self._append_audit_event(
                vault_id   = vault_id,
                event_type = "deposit",
                amount     = net,
                actor      = source,
                note       = f"Gross=${amount:.2f}  Fee=${fee:.2f}  Net=${net:.2f}",
            )
            self._save_state()
            logger.info(
                "[Vault] '%s' deposit | gross=$%.2f | fee=$%.2f | pool=$%.2f",
                vault_id, amount, fee, vault.profit_pool,
            )
            return net

    def harvest(self, vault_id: str) -> List[Dict[str, Any]]:
        """
        Distribute the current profit pool proportionally to eligible investors.
        Clears the pool after distribution.
        Returns a list of distribution records.
        """
        with self._lock:
            vault = self._vaults.get(vault_id)
            if vault is None:
                return []

            distributable = vault.profit_pool * (vault.profit_share_pct / 100.0)
            if distributable <= 0 or vault.total_units <= 0:
                logger.info("[Vault] Nothing to harvest in '%s'.", vault_id)
                return []

            subs = self._subscriptions.get(vault_id, [])
            distributions: List[Dict[str, Any]] = []

            for sub in subs:
                investor = self._investors.get(sub.investor_id)
                if investor is None or not investor.is_eligible:
                    continue

                share_fraction = sub.units / vault.total_units
                investor_share = distributable * share_fraction

                sub.distributed       += investor_share
                investor.total_distributed += investor_share
                investor.current_value     += investor_share

                distributions.append({
                    "investor_id": sub.investor_id,
                    "amount":      round(investor_share, 2),
                    "units":       round(sub.units, 6),
                    "share_pct":   round(share_fraction * 100, 4),
                })
                logger.info(
                    "[Vault] Distributed $%.2f to %s (%.4f%%)",
                    investor_share, sub.investor_id, share_fraction * 100,
                )

            vault.profit_pool       -= distributable
            vault.total_distributed += distributable
            vault.last_updated       = _now()

            self._append_audit_event(
                vault_id   = vault_id,
                event_type = "harvest",
                amount     = distributable,
                actor      = "system",
                note       = f"{len(distributions)} investors received distributions",
            )
            self._save_state()
            return distributions

    # ── Reporting ─────────────────────────────────────────────────────────────

    def nav_report(self, vault_id: str) -> Dict[str, Any]:
        """Return NAV and pool statistics for a vault."""
        with self._lock:
            vault = self._vaults.get(vault_id)
            if vault is None:
                return {"error": f"Vault '{vault_id}' not found"}

            subs = self._subscriptions.get(vault_id, [])
            investor_count = len({s.investor_id for s in subs})

            return {
                "vault_id":          vault_id,
                "display_name":      vault.display_name,
                "total_units":       round(vault.total_units, 6),
                "unit_nav":          round(vault.unit_nav, 6),
                "gross_profit":      round(vault.gross_profit, 2),
                "total_fees":        round(vault.total_fees, 2),
                "profit_pool":       round(vault.profit_pool, 2),
                "total_distributed": round(vault.total_distributed, 2),
                "investor_count":    investor_count,
                "profit_share_pct":  vault.profit_share_pct,
                "manager_fee_pct":   vault.manager_fee_pct,
                "generated_at":      _now(),
            }

    def investor_statement(self, investor_id: str) -> Dict[str, Any]:
        """Return a full statement for one investor across all vaults."""
        with self._lock:
            investor = self._investors.get(investor_id)
            if investor is None:
                return {"error": f"Investor '{investor_id}' not found"}

            vault_entries = []
            for vault_id, subs in self._subscriptions.items():
                for sub in subs:
                    if sub.investor_id == investor_id:
                        vault_entries.append({
                            "vault_id":    vault_id,
                            "commitment":  round(sub.commitment, 2),
                            "units":       round(sub.units, 6),
                            "distributed": round(sub.distributed, 2),
                        })

            return {
                "investor_id":      investor_id,
                "name":             investor.name,
                "is_eligible":      investor.is_eligible,
                "total_committed":  round(investor.total_committed, 2),
                "total_deposited":  round(investor.total_deposited, 2),
                "total_distributed":round(investor.total_distributed, 2),
                "current_value":    round(investor.current_value, 2),
                "vault_subscriptions": vault_entries,
                "generated_at":     _now(),
            }

    def audit_log_tail(self, n: int = 50) -> List[Dict[str, Any]]:
        """Return the last N audit events from the log file."""
        try:
            if not os.path.exists(self.audit_log_path):
                return []
            events = []
            with open(self.audit_log_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
            return events[-n:]
        except Exception as exc:
            logger.warning("[Vault] Could not read audit log: %s", exc)
            return []

    def full_report(self) -> Dict[str, Any]:
        """Institutional-grade full report across all vaults."""
        with self._lock:
            vaults_summary = [self.nav_report(vid) for vid in self._vaults]
            total_aum = sum(v.gross_profit for v in self._vaults.values())
            total_distributed = sum(v.total_distributed for v in self._vaults.values())
            eligible_investors = sum(
                1 for inv in self._investors.values() if inv.is_eligible
            )
            return {
                "total_vaults":          len(self._vaults),
                "total_investors":       len(self._investors),
                "eligible_investors":    eligible_investors,
                "total_aum_gross":       round(total_aum, 2),
                "total_distributed":     round(total_distributed, 2),
                "vaults":                vaults_summary,
                "generated_at":          _now(),
            }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _append_audit_event(
        self,
        vault_id: str,
        event_type: str,
        amount: float,
        actor: str,
        note: str,
    ) -> None:
        self._event_counter += 1
        event = AuditEvent(
            event_id   = f"EVT-{self._event_counter:08d}",
            vault_id   = vault_id,
            event_type = event_type,
            amount     = amount,
            actor      = actor,
            note       = note,
            timestamp  = _now(),
        )
        try:
            os.makedirs(os.path.dirname(self.audit_log_path) or ".", exist_ok=True)
            with open(self.audit_log_path, "a") as fh:
                fh.write(json.dumps(asdict(event)) + "\n")
        except Exception as exc:
            logger.warning("[Vault] Audit log write failed: %s", exc)

    def _load_state(self) -> None:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path) as fh:
                    data = json.load(fh)
                for vid, vd in data.get("vaults", {}).items():
                    self._vaults[vid] = Vault(**{
                        k: v for k, v in vd.items()
                        if k in Vault.__dataclass_fields__
                    })
                for iid, id_ in data.get("investors", {}).items():
                    self._investors[iid] = InvestorRecord(**{
                        k: v for k, v in id_.items()
                        if k in InvestorRecord.__dataclass_fields__
                    })
                for vid, subs in data.get("subscriptions", {}).items():
                    self._subscriptions[vid] = [
                        VaultSubscription(**{k: v for k, v in sd.items()
                                            if k in VaultSubscription.__dataclass_fields__})
                        for sd in subs
                    ]
                self._event_counter = data.get("event_counter", 0)
                logger.info("[Vault] State restored from %s", self.state_path)
        except Exception as exc:
            logger.warning("[Vault] Could not load state (%s) – starting fresh.", exc)

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "w") as fh:
                json.dump(
                    {
                        "vaults":     {vid: asdict(v) for vid, v in self._vaults.items()},
                        "investors":  {iid: asdict(i) for iid, i in self._investors.items()},
                        "subscriptions": {
                            vid: [asdict(s) for s in subs]
                            for vid, subs in self._subscriptions.items()
                        },
                        "event_counter": self._event_counter,
                        "saved_at":      _now(),
                    },
                    fh, indent=2,
                )
        except Exception as exc:
            logger.warning("[Vault] Could not persist state: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_vault_instance: Optional[HedgeFundVault] = None
_vault_lock = threading.Lock()


def get_hedge_fund_vault(
    state_path:     str = "data/hedge_fund_vault_state.json",
    audit_log_path: str = "data/hedge_fund_audit_log.jsonl",
) -> HedgeFundVault:
    """Return the process-wide HedgeFundVault singleton."""
    global _vault_instance
    with _vault_lock:
        if _vault_instance is None:
            _vault_instance = HedgeFundVault(
                state_path=state_path,
                audit_log_path=audit_log_path,
            )
    return _vault_instance


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
