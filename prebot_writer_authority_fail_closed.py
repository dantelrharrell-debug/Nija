"""Fail-closed .pth entry for NIJA pre-bot writer authority acquisition."""

from __future__ import annotations

import logging
import os
from typing import Any

import prebot_writer_authority_bootstrap as bootstrap

logger = logging.getLogger("nija.prebot_writer_authority_fail_closed")
_MARKER = "20260710ab"


def install() -> Any:
    """Run pre-bot authority and install reviewed live-runtime guards.

    Python's ``site`` module normally reports and swallows exceptions raised by a
    ``.pth`` import line. A live trading process must never continue after early
    writer-authority or venue-readiness installation failure, so this boundary
    exits the process directly. Non-target processes are returned immediately by
    the underlying bootstrap.
    """

    try:
        runtime = bootstrap.install()
        if runtime is not None:
            import venue_readiness_execution_repair_patch as venue_repair

            venue_repair.install()
            logger.warning(
                "PREBOT_VENUE_READINESS_REPAIR_READY marker=20260710ae"
            )
        return runtime
    except BaseException as exc:
        # Only the configured live NIJA entrypoint is allowed to terminate here.
        # Health checks, tests and build helpers are excluded by _target_process().
        if not bootstrap._target_process():
            return None

        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
        message = f"{type(exc).__name__}:{exc}"
        logger.critical(
            "PREBOT_WRITER_AUTHORITY_FATAL marker=%s error=%s "
            "trading_remains_fail_closed=true",
            _MARKER,
            message,
            exc_info=True,
        )
        print(
            f"[NIJA-PRINT] PREBOT_WRITER_AUTHORITY_FATAL marker={_MARKER} "
            f"error={message[:240]} trading_remains_fail_closed=true",
            flush=True,
        )
        os._exit(78)


__all__ = ["install"]
