"""Private single-instance checkout journal; never shares trading or entitlement state."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import ipaddress
import os
from pathlib import Path
from os.path import ismount
import secrets
import sqlite3
import time
from typing import Any, Iterator

OWNER_COOKIE = "__Host-nija-checkout-owner"


class CheckoutDenied(Exception):
    """A bounded, retryable or operator-review checkout denial."""

    def __init__(self, reason: str, status: int = 503):
        super().__init__(reason)
        self.status = status


def client_identity(request: Any, prefix: str = "NIJA_GAME") -> str:
    """Trust raw peer by explicit direct policy, or one stripped header from an allowlisted proxy."""
    mode = os.getenv(prefix + "_INGRESS_MODE")
    peer = ipaddress.ip_address(request.environ.get("REMOTE_ADDR", ""))
    if mode == "direct":
        # Direct policy means no reverse proxy; ignore all caller-supplied forwarding.
        return str(peer)
    if mode != "proxy":
        raise CheckoutDenied("reviewed_ingress_required")
    networks = os.getenv(prefix + "_TRUSTED_PROXY_CIDRS", "").split(",")
    if not any(peer in ipaddress.ip_network(net.strip()) for net in networks if net.strip()):
        raise CheckoutDenied("untrusted_ingress", 403)
    # Ingress MUST overwrite X-Forwarded-For with exactly one verified address.
    # Do not trust an arbitrary leftmost address or apply ProxyFix globally.
    value = request.headers.get("X-Forwarded-For", "")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as error:
        raise CheckoutDenied("invalid_forwarded_identity", 403) from error


def digest(value: str) -> str:
    """Hash private ownership and client identity before indexing."""
    return hashlib.sha256(value.encode()).hexdigest()


class CheckoutStore:
    """Durable quotas and immutable reservations on a preprovisioned private disk file."""

    def __init__(self, path: str):
        target = Path(path)
        mount = Path(os.getenv("NIJA_GAME_CHECKOUT_MOUNT", ""))
        # Check raw components before resolve: resolving first hides traversal and
        # symlinks. Configuration must name an existing private journal on the disk.
        if ".." in target.parts or ".." in mount.parts:
            raise CheckoutDenied("dedicated_checkout_mount_required")
        if any(p.is_symlink() for p in [target, *target.parents, mount, *mount.parents]):
            raise CheckoutDenied("private_checkout_storage_required")
        try:
            resolved_target = target.resolve(strict=True)
            resolved_mount = mount.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise CheckoutDenied("private_checkout_storage_required") from error
        if (not mount.is_absolute() or mount == Path("/") or not ismount(mount)
                or not resolved_target.is_relative_to(resolved_mount)):
            raise CheckoutDenied("dedicated_checkout_mount_required")
        if not target.is_absolute() or not target.is_file() or any(p.is_symlink() for p in [target, *target.parents]):
            raise CheckoutDenied("private_checkout_storage_required")
        if (target.stat().st_uid != os.geteuid() or target.stat().st_mode & 0o077
                or target.parent.stat().st_uid != os.geteuid() or target.parent.stat().st_mode & 0o077):
            raise CheckoutDenied("private_checkout_storage_required")
        self.path = str(resolved_target)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS checkout_limits (bucket TEXT PRIMARY KEY, started INTEGER, count INTEGER)")
            db.execute("""CREATE TABLE IF NOT EXISTS checkout_reservations (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, attempt TEXT NOT NULL, origin TEXT NOT NULL,
                proof TEXT NOT NULL, created INTEGER NOT NULL, lease INTEGER NOT NULL, calls INTEGER NOT NULL,
                url TEXT, session TEXT, UNIQUE(owner, attempt, origin))""")

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        """Serialize journal transitions across workers; release before provider I/O."""
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def quota(db: sqlite3.Connection, bucket: str, maximum: int, window: int, now: int) -> None:
        """Consume one persisted fixed-window allowance inside the caller's transaction."""
        row = db.execute("SELECT * FROM checkout_limits WHERE bucket=?", (bucket,)).fetchone()
        count = row["count"] + 1 if row and now - row["started"] < window else 1
        started = row["started"] if row and now - row["started"] < window else now
        if count > maximum:
            raise CheckoutDenied("checkout_rate_limited", 429)
        db.execute("INSERT OR REPLACE INTO checkout_limits VALUES (?,?,?)", (bucket, started, count))

    def throttle(self, client: str) -> None:
        """Bound all submissions, including cookie bootstrap, before any provider calls."""
        now = int(time.time())
        with self.db() as db:
            db.execute("DELETE FROM checkout_limits WHERE started < ?", (now - 7200,))
            self.quota(db, "requests:global", 300, 60, now)
            self.quota(db, "requests:" + digest(client), 30, 60, now)

    def reserve(self, owner: str, attempt: str, origin: str, client: str) -> dict:
        """Reuse a browser-owned completed attempt; never replace expired/ambiguous sessions."""
        now = int(time.time())
        with self.db() as db:
            row = db.execute("SELECT * FROM checkout_reservations WHERE owner=? AND attempt=? AND origin=?",
                             (digest(owner), attempt, origin)).fetchone()
            if row and row["url"]:
                return dict(row)
            if row and (now - row["created"] >= 23 * 3600 or row["calls"] >= 3):
                raise CheckoutDenied("checkout_requires_review", 409)
            if row and row["lease"] > now:
                raise CheckoutDenied("checkout_in_progress", 409)
            self.quota(db, "provider:global", 100, 3600, now)
            self.quota(db, "provider:client:" + digest(client), 10, 3600, now)
            self.quota(db, "provider:owner:" + digest(owner), 5, 3600, now)
            if row:
                db.execute("UPDATE checkout_reservations SET lease=?, calls=calls+1 WHERE id=?", (now + 120, row["id"]))
            else:
                if db.execute("SELECT COUNT(*) FROM checkout_reservations").fetchone()[0] >= 10000:
                    raise CheckoutDenied("checkout_capacity_requires_review")
                reservation_id, proof = secrets.token_hex(32), secrets.token_hex(32)
                db.execute("INSERT INTO checkout_reservations VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (reservation_id, digest(owner), attempt, origin, proof, now, now + 120, 1, None, None))
                row = db.execute("SELECT * FROM checkout_reservations WHERE id=?", (reservation_id,)).fetchone()
            return dict(row)

    def finish(self, reservation_id: str, url: str, session: str) -> None:
        """Persist result before responding; an interrupted response is safely replayable."""
        with self.db() as db:
            row = db.execute("SELECT * FROM checkout_reservations WHERE id=?", (reservation_id,)).fetchone()
            if row["session"] and (row["session"] != session or row["url"] != url):
                raise CheckoutDenied("checkout_result_conflict")
            db.execute("UPDATE checkout_reservations SET url=?,session=?,lease=0 WHERE id=?", (url, session, reservation_id))
