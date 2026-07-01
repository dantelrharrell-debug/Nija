"""Prevent malformed logging calls from breaking Railway diagnostics."""

from __future__ import annotations

import logging

_ORIGINAL_GET_MESSAGE = None
_INSTALLED = False


def install() -> None:
    global _ORIGINAL_GET_MESSAGE, _INSTALLED
    if _INSTALLED:
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


def install_import_hook() -> None:
    install()
