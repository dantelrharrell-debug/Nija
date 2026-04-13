"""
NIJA User Nonce Manager
=======================

Backward-compatibility shim — delegates everything to DistributedNonceManager.

All per-user nonce logic has been moved to ``DistributedNonceManager``.
This module is retained so existing import sites continue to work unchanged.
New code should import from ``bot.distributed_nonce_manager`` directly.
"""

from __future__ import annotations

import glob as _glob
import logging
import os
import threading
from typing import Dict, Optional

logger = logging.getLogger("nija.nonce")

# Data directory (retained for _wipe_all_nonce_files compatibility)
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _get_dnm():
    """Lazily return the DistributedNonceManager singleton."""
    try:
        from bot.distributed_nonce_manager import get_distributed_nonce_manager
    except ImportError:
        from distributed_nonce_manager import get_distributed_nonce_manager  # type: ignore
    return get_distributed_nonce_manager()


class UserNonceManager:
    """
    Per-user nonce manager — thin delegation layer over DistributedNonceManager.

    Every method routes through ``get_distributed_nonce_manager()`` so all keys
    get the same institutional-grade monotonic guarantees (Redis or file/fcntl).
    """

    def __init__(self) -> None:
        os.makedirs(_data_dir, exist_ok=True)
        if os.environ.get("NIJA_FORCE_NONCE_RESYNC", "").strip() == "1":
            self._wipe_all_nonce_files()
            logger.info(
                "UserNonceManager: NIJA_FORCE_NONCE_RESYNC=1 — "
                "all user nonce state files wiped"
            )
        logger.info("UserNonceManager initialised (delegates to DistributedNonceManager)")

    # ── Delegation interface ──────────────────────────────────────────────────

    def get_nonce(self, user_id: str) -> int:
        """Return next strictly-increasing nonce for *user_id*'s API key."""
        return _get_dnm().get_nonce(user_id)

    def record_nonce_error(self, user_id: str) -> bool:
        """Forward nonce rejection to the distributed manager for recovery."""
        _get_dnm().record_error(user_id)
        return True  # recovery is handled internally

    def record_success(self, user_id: str, nonce: int) -> None:
        """Record that Kraken accepted *nonce* for *user_id*."""
        _get_dnm().record_success(user_id, nonce)

    def get_last_nonce(self, user_id: str = "") -> int:
        """Return the last issued nonce without advancing (diagnostic)."""
        return _get_dnm().get_last_nonce(user_id)

    def reset_user(self, user_id: str) -> None:
        """Hard-reset nonce tracking for *user_id* (call after key rotation)."""
        _get_dnm().reset_key(user_id)

    def get_stats(self, user_id: str) -> Dict:
        """Return diagnostic statistics for *user_id*."""
        dnm = _get_dnm()
        return {
            "user_id":    user_id,
            "last_nonce": dnm.get_last_nonce(user_id),
            "backend":    "redis" if dnm._redis is not None else "file",
        }

    # ── Compatibility stubs ───────────────────────────────────────────────────

    def begin_request(self) -> None:
        """No-op: compatibility stub."""

    def end_request(self) -> None:
        """No-op: compatibility stub."""

    # ── File-wipe helpers (retained for force-resync) ─────────────────────────

    def _wipe_all_nonce_files(self) -> None:
        """Remove all per-user nonce state files."""
        pattern = os.path.join(_data_dir, "kraken_nonce_*.state")
        for path in _glob.glob(pattern):
            if os.path.basename(path) == "kraken_nonce.state":
                continue  # never delete the platform state file
            try:
                os.remove(path)
                logger.debug("UserNonceManager: removed %s", path)
            except OSError as exc:
                logger.warning("UserNonceManager: could not remove %s: %s", path, exc)


# ── Module-level singleton ────────────────────────────────────────────────────

_user_nonce_manager: Optional[UserNonceManager] = None
_init_lock = threading.Lock()


def get_user_nonce_manager() -> UserNonceManager:
    """Return the process-global UserNonceManager singleton."""
    global _user_nonce_manager
    with _init_lock:
        if _user_nonce_manager is None:
            _user_nonce_manager = UserNonceManager()
    return _user_nonce_manager


def force_resync_all_user_nonces() -> None:
    """Wipe all per-user nonce state files so every USER broker starts fresh."""
    # Walk the registry and destroy every per-key instance
    try:
        from bot.global_kraken_nonce import _KEY_REGISTRY, _KEY_REGISTRY_LOCK
        with _KEY_REGISTRY_LOCK:
            keys = list(_KEY_REGISTRY.keys())
        from bot.global_kraken_nonce import KrakenNonceManager
        for k in keys:
            KrakenNonceManager.destroy_instance(key_id=k)
    except Exception as exc:
        logger.debug("force_resync_all_user_nonces: registry clear error: %s", exc)
    get_user_nonce_manager()._wipe_all_nonce_files()
    logger.info("force_resync_all_user_nonces: all user nonce state cleared")


__all__ = [
    "UserNonceManager",
    "get_user_nonce_manager",
    "force_resync_all_user_nonces",
]

