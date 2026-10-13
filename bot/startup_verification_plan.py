"""Bounded startup terms and explicit operator approval; no order submission."""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Mapping


class StartupPlanError(RuntimeError):
    """The exact bounded startup plan is missing, invalid or unapproved."""


def decimal_value(value: Any) -> Decimal:
    """Parse a finite broker/plan decimal without binary floating-point rounding."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise StartupPlanError("startup_plan_decimal_invalid") from None
    if not result.is_finite():
        raise StartupPlanError("startup_plan_decimal_invalid")
    return result


@dataclass(frozen=True)
class StartupVerificationPlan:
    """Immutable spot terms; fees are included in the maximum USD cash debit."""

    account_fingerprint: str
    api_key_fingerprint: str
    symbol: str
    pair: str
    budget_usd: str
    entry_limit: str
    base_quantity: str
    fee_rate_max: str
    fee_cash_reserve_usd: str
    stop_trigger: str
    stop_limit: str
    close_limit: str
    base_quantum: str
    minimum_base: str
    minimum_quote: str
    expires_at_epoch: float

    def validate(self) -> None:
        """Reject an unbounded, leveraged, malformed or over-budget description."""
        for fingerprint, length in ((self.account_fingerprint, 64), (self.api_key_fingerprint, 128)):
            if not isinstance(fingerprint, str) or len(fingerprint) != length or any(
                x not in "0123456789abcdef" for x in fingerprint
            ):
                raise StartupPlanError("startup_plan_identity_invalid")
        if not self.symbol.endswith("-USD") or self.symbol.count("-") != 1 or not self.pair:
            raise StartupPlanError("startup_plan_requires_USD_spot_pair")
        values = {name: decimal_value(getattr(self, name)) for name in (
            "budget_usd", "entry_limit", "base_quantity", "fee_rate_max", "fee_cash_reserve_usd",
            "stop_trigger", "stop_limit", "close_limit", "base_quantum", "minimum_base", "minimum_quote",
        )}
        if any(value <= 0 for key, value in values.items() if key not in {"fee_rate_max", "fee_cash_reserve_usd"}):
            raise StartupPlanError("startup_plan_terms_nonpositive")
        if not 0 <= values["fee_rate_max"] < 1 or values["fee_cash_reserve_usd"] < 0:
            raise StartupPlanError("startup_plan_fee_bound_invalid")
        if not values["stop_limit"] <= values["stop_trigger"] < values["close_limit"] <= values["entry_limit"]:
            raise StartupPlanError("startup_plan_protective_prices_invalid")
        quantity = values["base_quantity"]
        if quantity % values["base_quantum"] != 0 or quantity < values["minimum_base"]:
            raise StartupPlanError("startup_plan_volume_precision_or_minimum_invalid")
        if quantity * values["stop_limit"] < values["minimum_quote"]:
            raise StartupPlanError("startup_plan_protective_exit_below_minimum")
        if self.maximum_cash_debit() > values["budget_usd"]:
            raise StartupPlanError("startup_plan_all_in_budget_exceeded")
        if not math.isfinite(float(self.expires_at_epoch)) or self.expires_at_epoch <= 0:
            raise StartupPlanError("startup_plan_expiry_invalid")

    def maximum_cash_debit(self) -> Decimal:
        """Include entry price bound, worst published fee rate and cash fee reserve."""
        return (decimal_value(self.entry_limit) * decimal_value(self.base_quantity)
                * (1 + decimal_value(self.fee_rate_max)) + decimal_value(self.fee_cash_reserve_usd))

    def digest(self) -> str:
        """Bind approval to every exact term, account, key and expiry."""
        data = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(data.encode()).hexdigest()

    def order_parameters(self, leg: str, *, owned_base: Any = None) -> dict[str, Any]:
        """Describe bounded orders; this method never submits an order."""
        self.validate()
        if leg == "entry":
            quantity = decimal_value(self.base_quantity)
            data = {"type": "buy", "ordertype": "limit", "price": self.entry_limit, "timeinforce": "FOK"}
        elif leg in {"protect", "close"}:
            quantity = decimal_value(owned_base)
            if not 0 < quantity <= decimal_value(self.base_quantity):
                raise StartupPlanError("startup_exit_owned_quantity_invalid")
            quantum = decimal_value(self.base_quantum)
            quantity = (quantity / quantum).to_integral_value(rounding=ROUND_DOWN) * quantum
            if quantity < decimal_value(self.minimum_base):
                raise StartupPlanError("startup_exit_below_broker_minimum")
            exit_price = self.stop_limit if leg == "protect" else self.close_limit
            if quantity * decimal_value(exit_price) < decimal_value(self.minimum_quote):
                raise StartupPlanError("startup_exit_below_broker_quote_minimum")
            if leg == "protect":
                data = {"type": "sell", "ordertype": "stop-loss-limit", "price": self.stop_trigger,
                        "price2": self.stop_limit, "timeinforce": "GTC"}
            else:
                data = {"type": "sell", "ordertype": "limit", "price": self.close_limit, "timeinforce": "FOK"}
        else:
            raise StartupPlanError("startup_order_leg_invalid")
        # Kraken accepts UUIDs or free ASCII text of at most 18 characters.
        client_id = hashlib.sha256((self.digest() + ":" + leg).encode()).hexdigest()[:18]
        data.update(pair=self.pair, volume=str(quantity), oflags="fciq", cl_ord_id=client_id)
        return data


def load_startup_approval(identity: Any, *, symbol: str, path: Path | None = None,
                          permit_exit_after_expiry: bool = False) -> StartupVerificationPlan:
    """Read a private operator approval; a planning cap never grants permission."""
    target = path or Path(os.environ.get("NIJA_STARTUP_APPROVAL_PATH", "/data/startup_verification_approval.json"))
    if not target.is_absolute() or target.is_symlink():
        raise StartupPlanError("startup_approval_path_invalid")
    try:
        # Inspect and read the same descriptor; a replaced symlink cannot turn
        # the approval check into a read of a different file.
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid():
                raise StartupPlanError("startup_approval_file_not_private")
            if info.st_size > 16384:
                raise StartupPlanError("startup_approval_file_oversized")
            raw = handle.read(16385)
            if len(raw.encode("utf-8")) > 16384:
                raise StartupPlanError("startup_approval_file_oversized")
            receipt = json.loads(raw)
        if (not isinstance(receipt, Mapping) or receipt.get("approved") is not True
                or not str(receipt.get("approved_by") or "").strip()
                or receipt.get("ownership_verified") is not True):
            raise StartupPlanError("startup_exact_order_or_ownership_not_approved")
        plan = StartupVerificationPlan(**dict(receipt.get("plan") or {}))
        plan.validate()
        if receipt.get("approved_plan_digest") != plan.digest():
            raise StartupPlanError("startup_approval_terms_changed")
        if (plan.account_fingerprint != identity.account_fingerprint
                or plan.api_key_fingerprint != identity.api_key_fingerprint or plan.symbol != symbol):
            raise StartupPlanError("startup_approval_account_key_or_symbol_mismatch")
        observed = float(identity.observed_at_epoch)
        now = time.time()
        if not math.isfinite(observed) or not 0 <= now - observed <= 30:
            raise StartupPlanError("startup_approval_identity_stale")
        if not permit_exit_after_expiry and now >= plan.expires_at_epoch:
            raise StartupPlanError("startup_approval_expired")
        approved_at = float(receipt.get("approved_at_epoch") or 0)
        if not math.isfinite(approved_at) or not 0 < approved_at <= now + 60:
            raise StartupPlanError("startup_approval_timestamp_invalid")
        maximum = os.environ.get("NIJA_STARTUP_MAX_CASH_DEBIT_USD")
        if maximum is None or decimal_value(maximum) <= 0 or decimal_value(plan.budget_usd) > decimal_value(maximum):
            raise StartupPlanError("startup_operator_cash_ceiling_missing_or_exceeded")
        if receipt.get("bounded_entry_validated") is not True or receipt.get("native_exit_validated") is not True:
            raise StartupPlanError("startup_bounded_entry_or_exit_preflight_missing")
        return plan
    except StartupPlanError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        raise StartupPlanError("startup_approval_unavailable") from None


def enforce_bounded_startup_parameters(plan: StartupVerificationPlan, proposed: Mapping[str, Any],
                                       leg: str, *, owned_base: Any = None) -> dict[str, Any]:
    """Apply a final price/volume envelope without increasing risk-sized volume."""
    exact = plan.order_parameters(leg, owned_base=owned_base)
    if proposed.get("pair") != plan.pair or proposed.get("type") != exact["type"]:
        raise StartupPlanError("startup_order_account_pair_or_side_changed")
    if str(proposed.get("leverage") or "none").lower() not in {"none", "1", "1:1"}:
        raise StartupPlanError("startup_margin_order_forbidden")
    incoming = decimal_value(proposed.get("volume"))
    permitted = decimal_value(exact["volume"])
    if incoming < permitted:
        raise StartupPlanError("startup_order_would_increase_risk_sized_volume")
    if leg == "entry" and time.time() >= plan.expires_at_epoch:
        raise StartupPlanError("startup_approval_expired")
    # No post-only/market fallback, leverage, quote-volume flags or independent
    # conditional child can escape the approved startup description.
    return exact
