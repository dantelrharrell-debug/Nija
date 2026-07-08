from __future__ import annotations

try:
    from bot.capital_authority_live_total_v2_patch import install_import_hook, install  # type: ignore
except Exception:
    from capital_authority_live_total_v2_patch import install_import_hook, install  # type: ignore
