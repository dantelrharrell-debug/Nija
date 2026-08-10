"""Compatibility installer for writer recovery v81 + single-owner v82."""
from __future__ import annotations

from bot.writer_recovery_epoch_core_v81_impl import *  # noqa: F401,F403
from bot.writer_recovery_epoch_core_v81_impl import install_import_hook as _install_v81


def install_import_hook() -> bool:
    v81_ok = bool(_install_v81())
    try:
        from bot.writer_single_owner_convergence_v82_patch import install_import_hook as _install_v82
        v82_ok = bool(_install_v82())
    except Exception:
        v82_ok = False
    return bool(v81_ok and v82_ok)


def install() -> bool:
    return install_import_hook()
