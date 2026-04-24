"""
bot.risk — Unified risk and position-sizing package
====================================================

Public API
----------
calculate_position_size   : fee-aware, 10-step sizer (position_sizer.py)
tre_compute_position_size : TRE-aware wrapper (sizing.py)
allocate_capital          : execution-ready position dict (sizing.py)
"""
from bot.risk.sizing import (  # noqa: F401
    calculate_position_size,
    tre_compute_position_size,
    allocate_capital,
)
