"""Shared SQLite location for user, session, email-token and 2FA state."""

import os


def auth_database_path(db_path: str | None = None) -> str:
    """Use an explicit path, then the configured mount, then the legacy path.

    The caller provisions the parent and migrates existing state separately.
    Never create directories or silently copy a legacy database at startup.
    """
    if db_path is not None:
        if not db_path.strip():
            raise ValueError("Authentication database path cannot be empty")
        return db_path
    configured = os.getenv("NIJA_AUTH_USER_DB_PATH", "users.db")
    if not configured.strip():
        raise ValueError("NIJA_AUTH_USER_DB_PATH cannot be empty")
    return configured
