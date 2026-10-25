"""Read-only, credential-scoped Kraken nonce error diagnostics.

Never issue a nonce, reset a counter, or use a platform/global nonce
manager to describe a different account's nonce state.
"""


def nonce_error_diagnostic(broker, *, parenthesized=False):
    """Describe the account's last *issued* nonce, not the rejected request nonce.

    The distributed manager's get_last_nonce may return zero when its backend
    is unavailable, so zero is treated as unverified rather than authoritative.
    No account identifier, key material, or secret is included.
    """
    manager = getattr(broker, "nonce_manager", None)
    key_id = getattr(broker, "api_key_id", None)
    value = "unavailable"
    scope = "unverified"
    getter = getattr(manager, "get_last_nonce", None)
    if key_id and callable(getter):
        try:
            observed = int(getter(key_id))
            if observed > 0:
                value = str(observed)
                scope = "account"
        except (TypeError, ValueError, RuntimeError, OSError):
            pass
        except Exception:
            # Diagnostics must never break the broker's fail-closed error path.
            pass
    body = f"last_issued_nonce={value} nonce_scope={scope}"
    return f" ({body})" if parenthesized else f" {body}"
