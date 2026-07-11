"""Fail-closed entry for NIJA pre-bot writer authority acquisition.

Render zero-downtime deploys must expose process liveness before the replacement
instance waits for the existing writer to release its lease.  The Docker ``.pth``
hook therefore calls :func:`install` with ``defer_if_render=True``.  ``main.py``
then reaches the source bootstrap, which calls this installer normally and
acquires the exact same canonical writer authority before any ``bot.*`` import.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import prebot_writer_authority_bootstrap as bootstrap

logger = logging.getLogger("nija.prebot_writer_authority_fail_closed")
_MARKER = "20260710ab"
_DEFER_MARKER = "20260711a"


def _publish_fail_closed_state() -> None:
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"


def install(*, defer_if_render: bool = False) -> Any:
    """Acquire canonical authority or deliberately defer the Render ``.pth`` wait.

    Deferral is allowed only for the configured live NIJA entrypoint on Render.
    It does not grant authority: the process remains ``OFF`` with execution
    authority disabled until the source bootstrap calls ``install()`` without the
    deferral flag and the canonical Redis lease is acquired.
    """

    target = bootstrap._target_process()
    if defer_if_render and target and bootstrap._is_render_runtime():
        _publish_fail_closed_state()
        os.environ["NIJA_PREBOT_WRITER_AUTHORITY_READY"] = "0"
        os.environ["NIJA_PREBOT_WRITER_AUTHORITY_DEFERRED"] = "1"
        os.environ["NIJA_PREBOT_WRITER_AUTHORITY_DEFER_MARKER"] = _DEFER_MARKER
        logger.warning(
            "PREBOT_WRITER_AUTHORITY_DEFERRED marker=%s provider=render "
            "handoff=source_runtime_guard_bootstrap trading_remains_fail_closed=true",
            _DEFER_MARKER,
        )
        print(
            f"[NIJA-PRINT] PREBOT_WRITER_AUTHORITY_DEFERRED marker={_DEFER_MARKER} "
            "provider=render handoff=source_runtime_guard_bootstrap "
            "trading_remains_fail_closed=true",
            flush=True,
        )
        return None

    try:
        runtime = bootstrap.install()
        if runtime is not None:
            os.environ["NIJA_PREBOT_WRITER_AUTHORITY_DEFERRED"] = "0"
            import venue_readiness_execution_repair_patch as venue_repair

            venue_repair.install()
            logger.warning(
                "PREBOT_VENUE_READINESS_REPAIR_READY marker=20260710ae"
            )
        return runtime
    except BaseException as exc:
        # Python's site module reports and swallows exceptions raised by a .pth
        # import line.  The actual live entrypoint must instead terminate directly.
        if not target:
            return None

        _publish_fail_closed_state()
        os.environ["NIJA_PREBOT_WRITER_AUTHORITY_READY"] = "0"
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
