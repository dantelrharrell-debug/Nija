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
class ReconciledClose:
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


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", value))


def _decimal(value: object) -> bool:
    return (
        type(value) is Decimal and value.is_finite()
        and len(value.as_tuple().digits) <= 64 and abs(value.as_tuple().exponent) <= 64
    )


def _canonical(value: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 64
        return format(value.normalize(), "f") if value else "0"


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
            if saved == (payload, 0):
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
                    (scope, lot_id, hashlib.sha256(payload.encode()).hexdigest(),
                     proof.evidence_sha256),
                )
                return "quarantined"
            return "accepted"

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
