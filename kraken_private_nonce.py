"""Nonce ownership boundary for auxiliary Kraken authentication requests."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator


def _load_authority(api_key: str):
    """Resolve the existing runtime authority without a local fallback."""
    from bot.distributed_nonce_manager import get_distributed_nonce_manager, make_api_key_id
    from bot.execution_authority_context import assert_startup_write_authority
    from bot.global_kraken_nonce import get_kraken_api_lock

    assert_startup_write_authority()
    return get_distributed_nonce_manager(), make_api_key_id(api_key), get_kraken_api_lock()


@contextmanager
def coordinated_kraken_nonce(api_key: str) -> Iterator[int]:
    """Hold the runtime request lock from nonce allocation through response.

    Auxiliary services must use the authorized nonce-owning runtime. An
    unavailable authority blocks the request; no timestamp is substituted.
    Never lower or reset an existing key's high-water mark here.
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("Kraken nonce authority unavailable")
    manager, key_id, request_lock = _load_authority(api_key)
    with request_lock:
        nonce = manager.get_nonce(key_id)
        if type(nonce) is not int or not 0 < nonce < 2**64:
            raise RuntimeError("Kraken nonce authority unavailable")
        yield nonce
