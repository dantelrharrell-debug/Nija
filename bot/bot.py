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

import sys

from bot.bot_main import main


if __name__ == "__main__":
    sys.exit(main())
