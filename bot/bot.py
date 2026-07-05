"""Compatibility entrypoint for Railway/main.py.

Historically this file contained a small Coinbase REST sample loop.  main.py
runs ``bot.bot`` as ``__main__``, so that sample loop caused startup to enter a
Coinbase-only balance poller instead of NIJA's real APEX runtime.  It also threw
``'NoneType' object is not subscriptable`` when Coinbase account hydration
returned no account payload.

Keep this module as the stable import target, but delegate immediately to
``bot.bot_main``, which owns self-healing bootstrap, BootstrapFSM advancement,
and NijaCoreLoop startup.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger("nija.bot_entrypoint")

try:
    from bot.startup_authority_prereq_repair_patch import install_import_hook as _install_startup_authority_repair
    _install_startup_authority_repair()
    logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("STARTUP_AUTHORITY_PREREQ_REPAIR_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

try:
    from bot.bootstrap_i12_capital_authority_repair_patch import install_import_hook as _install_bootstrap_i12_ca_repair
    _install_bootstrap_i12_ca_repair()
    logger.warning("BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_INSTALL_REQUESTED source=bot_entrypoint")
except Exception as exc:
    logger.warning("BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_INSTALL_FAILED source=bot_entrypoint err=%s", exc)

from bot.bot_main import main


if __name__ == "__main__":
    sys.exit(main())
