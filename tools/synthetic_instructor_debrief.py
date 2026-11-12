"""Synthetic-only instructor debrief prototype. No imports from NIJA runtime.

Run: python3 tools/synthetic_instructor_debrief.py
Uses fictional in-memory rows only; does not read files, environment variables,
databases, network services, brokerage credentials, or production exports.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from html import escape


@dataclass(frozen=True)
class PracticeTrade:
    symbol: str
    side: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    entry_time: str
    exit_time: str
    planned_risk_rule: str
    exit_reason: str


SYNTHETIC_TRADE = PracticeTrade(
    symbol="BTC/USD (fictional)", side="BUY",
    entry_price=Decimal("50000"), exit_price=Decimal("49950"),
    quantity=Decimal("0.002"), entry_fee=Decimal("0.05"),
    exit_fee=Decimal("0.05"),
    entry_time="2026-01-01T12:00:00+00:00",
    exit_time="2026-01-01T12:18:00+00:00",
    planned_risk_rule="Review planned maximum loss before entering",
    exit_reason="Practice exit",
)


def build_debrief(trade: PracticeTrade) -> dict:
    """Calculate illustrative arithmetic; never certify actual fills or rule adherence."""
    if trade.side not in {"BUY", "SELL"}:
        raise ValueError("Unsupported trade side")
    if trade.quantity <= 0 or trade.entry_price <= 0 or trade.exit_price <= 0:
        raise ValueError("Prices and quantity must be positive")
    if trade.entry_fee < 0 or trade.exit_fee < 0:
        raise ValueError("Fees must be nonnegative")
    start = datetime.fromisoformat(trade.entry_time)
    end = datetime.fromisoformat(trade.exit_time)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Timezone-aware timestamps required")
    duration = int((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds())
    if duration < 0:
        raise ValueError("Exit precedes entry")
    direction = Decimal("1") if trade.side == "BUY" else Decimal("-1")
    gross = (trade.exit_price - trade.entry_price) * trade.quantity * direction
    net = gross - trade.entry_fee - trade.exit_fee
    return {
        "title": "NIJA Academy | Fictional instructor debrief",
        "symbol": trade.symbol,
        "side": trade.side,
        "duration_minutes": Decimal(duration) / Decimal("60"),
        "gross_result": gross,
        "modeled_fees": trade.entry_fee + trade.exit_fee,
        "illustrative_net_result": net,
        "exit_reason": trade.exit_reason,
        "planned_rule": trade.planned_risk_rule,
        "questions": [
            "What was the learning objective before entry?",
            "Did the learner define a maximum acceptable loss?",
            "What evidence would be needed to assess adherence to that rule?",
            "What would the learner change in the next practice round?",
        ],
        "limitations": (
            "Fictional educational example only. Assumes quantity in base units, "
            "USD quote/fees and unit contract multiplier. Not a broker statement, "
            "execution reconstruction, validated P&L, or rule-compliance finding."
        ),
    }


def render_text(report: dict) -> str:
    lines = [
        report["title"], "SYNTHETIC DATA ONLY | NOT FINANCIAL ADVICE",
        f'Symbol: {report["symbol"]} | Side: {report["side"]}',
        f'Duration (minutes): {report["duration_minutes"]}',
        f'Gross: {report["gross_result"]} | Modeled fees: {report["modeled_fees"]}',
        f'Illustrative net: {report["illustrative_net_result"]}',
        f'Exit reason: {report["exit_reason"]}',
        f'Learner plan: {report["planned_rule"]}',
        "Instructor discussion:",
    ]
    lines.extend(f"- {question}" for question in report["questions"])
    lines.append(report["limitations"])
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_text(build_debrief(SYNTHETIC_TRADE)))
