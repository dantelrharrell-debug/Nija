"""Prevent malformed logging calls from breaking Railway diagnostics."""

from __future__ import annotations

import logging

_ORIGINAL_GET_MESSAGE = None
_INSTALLED = False


def _install_sector_tier_hydration_repair() -> None:
    try:
        try:
            from bot.sector_tier_hydration_repair_patch import install_import_hook
        except ImportError:
            from sector_tier_hydration_repair_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logging.getLogger("nija.logging_format_guard").warning(
            "SECTOR_TIER_HYDRATION_REPAIR_INSTALL_REQUESTED"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "Sector/tier hydration repair unavailable: %s",
            exc,
        )


def install() -> None:
    global _ORIGINAL_GET_MESSAGE, _INSTALLED
    if _INSTALLED:
        _install_sector_tier_hydration_repair()
        return
    _ORIGINAL_GET_MESSAGE = logging.LogRecord.getMessage

    def _safe_get_message(self: logging.LogRecord) -> str:
        try:
            return _ORIGINAL_GET_MESSAGE(self)  # type: ignore[misc]
        except TypeError as exc:
            msg = str(self.msg)
            args = getattr(self, "args", None)
            return f"{msg} | logging_args={args!r} | logging_format_error={exc}"

    logging.LogRecord.getMessage = _safe_get_message  # type: ignore[assignment]
    _INSTALLED = True
    logging.getLogger("nija.logging_format_guard").warning("LOGGING_FORMAT_GUARD_INSTALLED")
    _install_sector_tier_hydration_repair()


def install_import_hook() -> None:
    install()
