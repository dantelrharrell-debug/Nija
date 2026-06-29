"""NIJA Python startup defaults.

This file is intentionally limited to safe environment normalization. Runtime
monkey-patching now lives in explicit startup modules such as
``bot.startup_runtime_safety`` so repeated imports cannot recursively wrap OKX
or strategy methods.
"""

from __future__ import annotations

import os


def _clean(value: str | None) -> str:
    text = str(value or "").strip().lstrip("\ufeff")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text.strip().strip('"').strip("'").strip()


# US OKX accounts require the US regional REST host. Normalize legacy global
# hosts before broker_manager initializes, while preserving any explicit custom
# non-global override.
_okx_base_url = _clean(os.getenv("OKX_BASE_URL")).rstrip("/")
if not _okx_base_url or _okx_base_url in {"https://www.okx.com", "https://openapi.okx.com"}:
    os.environ["OKX_BASE_URL"] = "https://us.okx.com"
os.environ.setdefault("OKX_US_REGION", "true")

# Normalize quoted Railway credential values without logging or exposing them.
for _name in (
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_API_PASSPHRASE",
    "OKX_PASSPHRASE",
):
    if _name in os.environ:
        os.environ[_name] = _clean(os.environ.get(_name))

# Runtime defaults used by the explicit startup safety module.
os.environ.setdefault("NIJA_STARTUP_POSITION_SYNC_ENABLED", "true")
os.environ.setdefault("NIJA_BROKER_SCOPED_POSITION_CAP", "true")
os.environ.setdefault("NIJA_PROFITABILITY_GUARD_ENABLED", "true")
os.environ.setdefault("NIJA_LOG_TRADE_DECISIONS", "true")
