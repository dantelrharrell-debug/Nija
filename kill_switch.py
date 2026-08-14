"""Legacy import compatibility for NIJA's canonical global kill switch.

The canonical implementation lives in :mod:`bot.kill_switch`.  Historically,
some runtime paths imported the same implementation as top-level
``kill_switch`` while others used ``bot.kill_switch``.  Loading the file under
both names creates two module objects and therefore two independent singleton
kill-switch instances, which can make activation/readiness consumers disagree.

This module deliberately owns no state.  It aliases the legacy import name to
the canonical module object so both import paths share exactly one singleton.
A genuine ``EMERGENCY_STOP`` file and all existing fail-closed behavior remain
unchanged in ``bot.kill_switch``.
"""

from __future__ import annotations

import importlib
import sys

_canonical = importlib.import_module("bot.kill_switch")
sys.modules[__name__] = _canonical
