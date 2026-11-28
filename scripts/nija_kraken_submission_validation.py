"""Read-only validation shared by the submission journal and backup verifier."""

import sqlite3
import time


def has_invalid_terminal_metadata(db: sqlite3.Connection) -> bool:
    """Check terminal metadata within the caller's consistent database view."""
    return db.execute(
        """SELECT 1 FROM submission_resolution AS r
           JOIN submission AS s ON s.intent_id=r.intent_id
           WHERE NOT COALESCE(
               r.terminal_status IN ('closed', 'canceled', 'expired')
               AND typeof(s.reserved_at) IN ('integer', 'real')
               AND typeof(r.observed_at) IN ('integer', 'real')
               AND s.reserved_at > 0
               AND r.observed_at BETWEEN s.reserved_at AND ?
               AND typeof(r.broker_evidence_sha256) = 'text'
               AND length(r.broker_evidence_sha256) = 64
               AND length(CAST(r.broker_evidence_sha256 AS BLOB)) = 64
               AND r.broker_evidence_sha256 NOT GLOB '*[^0-9a-f]*'
               AND typeof(r.ledger_evidence_sha256) = 'text'
               AND length(r.ledger_evidence_sha256) = 64
               AND length(CAST(r.ledger_evidence_sha256 AS BLOB)) = 64
               AND r.ledger_evidence_sha256 NOT GLOB '*[^0-9a-f]*',
               0
           )
           LIMIT 1""",
        (time.time(),),
    ).fetchone() is not None
