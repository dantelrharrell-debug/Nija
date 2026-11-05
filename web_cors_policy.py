"""Explicit browser origins for the shared authenticated web/mobile API."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

DEFAULT_WEB_ORIGINS = "https://nijaaitrading.com,https://www.nijaaitrading.com"


def allowed_web_origins() -> list[str]:
    """Load exact HTTP(S) origins; refuse wildcard and regex credential sharing."""
    origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", DEFAULT_WEB_ORIGINS).split(",")]
    for origin in origins:
        parsed = urlsplit(origin)
        if (not origin or parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                or any(character.isspace() or character in "*\\[](){}|^$?#" for character in origin)):
            raise ValueError("ALLOWED_ORIGINS must contain explicit HTTP(S) origins without paths or patterns")
        # Validate ports as well; urlsplit defers invalid-port errors.
        _ = parsed.port
    return origins
