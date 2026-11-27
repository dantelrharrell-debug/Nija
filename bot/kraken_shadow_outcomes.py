"""Offline learning inbox. Deliberately not wired into execution or live tuning."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
import json
import re
import sqlite3
from typing import Callable


@dataclass(frozen=True)
class CloseEconomics:
    """Independently reconciled whole-lot amounts in USD and the broker close time."""

    opening_notional_usd: Decimal
    gross_pnl_usd: Decimal
    execution_cost_usd: Decimal
    closed_at_epoch: int


@dataclass(frozen=True)
class ReconciledClose:
    """One complete, same-account close supplied by the offline evidence reader."""

    scope: str
    lot_id: str
    opening_intent_id: str
    opening_order_id: str
    closing_fill_ids: tuple[str, ...]
    opening_quantity: Decimal
    closed_quantity: Decimal
    net_return: Decimal
    symbol: str
    regime: str
    strategy: str
    evidence_sha256: str
    economics: CloseEconomics | None = None


@dataclass(frozen=True)
class OwnerDecision:
    """An authenticated review opinion, with no runtime authorization semantics."""

    scope: str
    decision_id: str
    owner_id: str
    snapshot_sha256: str
    decision: str
    decided_at_epoch: int


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", value))


def _decimal(value: object) -> bool:
    return (
        type(value) is Decimal and value.is_finite()
        and len(value.as_tuple().digits) <= 64 and abs(value.as_tuple().exponent) <= 64
    )


def _canonical(value: Decimal) -> str:
    if not value:
        return "0"
    fixed = format(value, "f")
    return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed

def _economics_payload(proof: ReconciledClose) -> str | None:
    economics = proof.economics
    if economics is None:
        return None
    return json.dumps({
        "opening_notional_usd": _canonical(economics.opening_notional_usd),
        "gross_pnl_usd": _canonical(economics.gross_pnl_usd),
        "execution_cost_usd": _canonical(economics.execution_cost_usd),
        "closed_at_epoch": economics.closed_at_epoch,
    }, sort_keys=True, separators=(",", ":"))


def _valid_economics(proof: ReconciledClose) -> bool:
    economics = proof.economics
    if economics is None:
        return True
    if type(economics) is not CloseEconomics or not all(_decimal(amount) for amount in (
        economics.opening_notional_usd, economics.gross_pnl_usd, economics.execution_cost_usd,
    )):
        return False
    if (economics.opening_notional_usd <= 0 or economics.execution_cost_usd < 0
            or type(economics.closed_at_epoch) is not int or not 0 < economics.closed_at_epoch < 253402300800):
        return False
    with localcontext() as ctx:
        # Accept reasonable reporting precision without failing exact decimal cost arithmetic.
        ctx.prec = 256
        net = economics.gross_pnl_usd - economics.execution_cost_usd
        return (net / economics.opening_notional_usd).quantize(Decimal("0.000000000001")) == (
            proof.net_return.quantize(Decimal("0.000000000001"))
        )


def _evidence_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class KrakenShadowOutcomes:
    """Store only outcomes supplied by an independently verified offline reader.

    The reader is a trusted dependency, not a network endpoint or a caller flag.
    It must resolve a same-account opening intent/order/lot and a complete,
    fee-reconciled set of closing fills, or return None. A terminal order status
    alone cannot implement that contract. Use a separate test/shadow database.
    """

    def __init__(
        self, path: str, *, read_reconciled_close: Callable[[str, str], ReconciledClose | None]
    ):
        self._path = path
        self._read = read_reconciled_close
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS shadow_outcome_v1 (
                    scope TEXT NOT NULL, lot_id TEXT NOT NULL, payload TEXT NOT NULL,
                    evidence TEXT NOT NULL, quarantined INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (scope, lot_id)
                );
                CREATE TABLE IF NOT EXISTS shadow_fill_v1 (
                    scope TEXT NOT NULL, fill_id TEXT NOT NULL, lot_id TEXT NOT NULL,
                    PRIMARY KEY (scope, fill_id)
                );
                CREATE TABLE IF NOT EXISTS shadow_economics_v1 (
                    scope TEXT NOT NULL, lot_id TEXT NOT NULL, payload TEXT NOT NULL,
                    evidence TEXT NOT NULL, PRIMARY KEY (scope, lot_id)
                );
                CREATE TABLE IF NOT EXISTS shadow_owner_decision_v1 (
                    scope TEXT NOT NULL, decision_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (scope, decision_id)
                );
                CREATE TABLE IF NOT EXISTS shadow_conflict_v1 (
                    scope TEXT NOT NULL, lot_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, evidence TEXT NOT NULL,
                    PRIMARY KEY (scope, lot_id, payload_sha256, evidence)
                );
            """)

    def observe(self, scope: str, lot_id: str) -> str:
        if not _identifier(scope) or not _identifier(lot_id):
            return "unverified"
        proof = self._read(scope, lot_id)
        if not self._valid(proof, scope, lot_id):
            return "unverified"

        payload = json.dumps({
            "opening_intent_id": proof.opening_intent_id,
            "opening_order_id": proof.opening_order_id,
            "closing_fill_ids": sorted(proof.closing_fill_ids),
            "quantity": _canonical(proof.closed_quantity),
            "net_return": _canonical(proof.net_return),
            "symbol": proof.symbol, "regime": proof.regime, "strategy": proof.strategy,
        }, sort_keys=True, separators=(",", ":"))
        with closing(sqlite3.connect(self._path)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT payload, quarantined FROM shadow_outcome_v1 WHERE scope=? AND lot_id=?",
                (scope, lot_id),
            ).fetchone()
            economics = _economics_payload(proof)
            prior_economics = db.execute(
                "SELECT payload FROM shadow_economics_v1 WHERE scope=? AND lot_id=?", (scope, lot_id),
            ).fetchone()
            economics_changed = (
                economics is not None and prior_economics is not None and prior_economics[0] != economics
            )
            if saved == (payload, 0) and not economics_changed:
                if economics is not None and prior_economics is None:
                    self._insert_economics(db, proof, economics)
                    return "enriched"
                return "duplicate"

            overlap = set()
            for fill_id in proof.closing_fill_ids:
                owner = db.execute(
                    "SELECT lot_id FROM shadow_fill_v1 WHERE scope=? AND fill_id=?",
                    (scope, fill_id),
                ).fetchone()
                if owner is not None and owner[0] != lot_id:
                    overlap.add(owner[0])

            if saved is None:
                db.execute(
                    "INSERT INTO shadow_outcome_v1 VALUES (?, ?, ?, ?, ?)",
                    (scope, lot_id, payload, proof.evidence_sha256, int(bool(overlap))),
                )
                if economics is not None and not overlap:
                    self._insert_economics(db, proof, economics)
            # Retain new claims even on conflict so a disputed fill cannot later
            # be admitted through an otherwise unrelated lot.
            db.executemany(
                "INSERT OR IGNORE INTO shadow_fill_v1 VALUES (?, ?, ?)",
                ((scope, fill_id, lot_id) for fill_id in proof.closing_fill_ids),
            )
            if saved is not None or overlap:
                db.executemany(
                    "UPDATE shadow_outcome_v1 SET quarantined=1 WHERE scope=? AND lot_id=?",
                    ((scope, affected) for affected in (overlap | {lot_id})),
                )
                db.execute(
                    "INSERT OR IGNORE INTO shadow_conflict_v1 VALUES (?, ?, ?, ?)",
                    (scope, lot_id, _evidence_digest((payload, economics)),
                     proof.evidence_sha256),
                )
                return "quarantined"
            return "accepted"

    @staticmethod
    def _insert_economics(db: sqlite3.Connection, proof: ReconciledClose, payload: str) -> None:
        db.execute(
            "INSERT INTO shadow_economics_v1 VALUES (?, ?, ?, ?)",
            (proof.scope, proof.lot_id, payload, proof.evidence_sha256),
        )

    @staticmethod
    def _valid(proof: object, scope: str, lot_id: str) -> bool:
        if type(proof) is not ReconciledClose or (proof.scope, proof.lot_id) != (scope, lot_id):
            return False
        fills = proof.closing_fill_ids
        return (
            all(_identifier(x) for x in (
                proof.opening_intent_id, proof.opening_order_id, proof.symbol,
                proof.strategy, proof.regime,
            ))
            and type(fills) is tuple and 0 < len(fills) <= 4096
            and all(_identifier(x) for x in fills) and len(set(fills)) == len(fills)
            and all(_decimal(x) for x in (
                proof.opening_quantity, proof.closed_quantity, proof.net_return,
            ))
            and proof.opening_quantity == proof.closed_quantity > 0
            and isinstance(proof.evidence_sha256, str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", proof.evidence_sha256))
            and _valid_economics(proof)
        )

    def snapshot(self, scope: str) -> list[dict]:
        """Return a full account-scoped snapshot for rebuilding disposable reports."""
        if not _identifier(scope):
            raise ValueError("explicit account scope required")
        with closing(sqlite3.connect(self._path)) as db:
            rows = db.execute(
                """SELECT lot_id, payload FROM shadow_outcome_v1
                   WHERE scope=? AND quarantined=0 ORDER BY lot_id""",
                (scope,),
            ).fetchall()
        return [{"lot_id": lot_id, **json.loads(payload)} for lot_id, payload in rows]


    def evaluation_snapshot(self, scope: str) -> list[dict]:
        """Return one bounded snapshot with exact evidence identities for offline review."""
        if not _identifier(scope):
            raise ValueError("explicit account scope required")
        with closing(sqlite3.connect(self._path)) as db:
            rows = db.execute(
                """SELECT o.lot_id, o.payload, o.evidence, e.payload, e.evidence
                   FROM shadow_outcome_v1 AS o LEFT JOIN shadow_economics_v1 AS e
                   ON o.scope=e.scope AND o.lot_id=e.lot_id
                   WHERE o.scope=? AND o.quarantined=0 ORDER BY o.lot_id LIMIT 10001""",
                (scope,),
            ).fetchall()
        if len(rows) > 10000:
            raise ValueError("evaluation snapshot exceeds offline review limit")
        return [
            {"lot_id": lot, **json.loads(payload), "evidence_sha256": evidence,
             "economics": json.loads(economics) if economics is not None else None,
             "economics_evidence_sha256": economics_evidence}
            for lot, payload, evidence, economics, economics_evidence in rows
        ]

    def record_owner_decision(
        self, decision: OwnerDecision, *, authenticate: Callable[[OwnerDecision], bool],
    ) -> str:
        """Append a verified decision about one exact offline evaluation snapshot."""
        if (type(decision) is not OwnerDecision
                or not all(_identifier(value) for value in (decision.scope, decision.decision_id, decision.owner_id))
                or not isinstance(decision.decision, str) or decision.decision not in {"retain_for_review", "reject"}
                or not isinstance(decision.snapshot_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", decision.snapshot_sha256)
                or type(decision.decided_at_epoch) is not int or not 0 < decision.decided_at_epoch < 253402300800
                or authenticate(decision) is not True):
            return "unverified"
        payload = json.dumps(vars(decision), sort_keys=True, separators=(",", ":"))
        with closing(sqlite3.connect(self._path)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload FROM shadow_owner_decision_v1 WHERE scope=? AND decision_id=?",
                (decision.scope, decision.decision_id),
            ).fetchone()
            if existing is not None:
                return "duplicate" if existing[0] == payload else "conflict"
            db.execute("INSERT INTO shadow_owner_decision_v1 VALUES (?, ?, ?)",
                       (decision.scope, decision.decision_id, payload))
        return "recorded"

    def owner_decisions(self, scope: str, snapshot_sha256: str) -> list[dict]:
        """Read owner decisions tied to the exact current snapshot."""
        with closing(sqlite3.connect(self._path)) as db:
            rows = db.execute(
                """SELECT payload FROM shadow_owner_decision_v1
                   WHERE scope=? AND json_extract(payload, '$.snapshot_sha256')=?
                   ORDER BY json_extract(payload, '$.decided_at_epoch'), decision_id""",
                (scope, snapshot_sha256),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
