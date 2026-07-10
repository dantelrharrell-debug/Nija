"""Prevent malformed logging calls from breaking Railway diagnostics.

This is the first patch module loaded by the repository's ``sitecustomize.py``.
Acquire the canonical Redis writer authority here before any runtime repair
monitor can observe or mutate live execution state.
"""

from __future__ import annotations

import logging
import os

_ORIGINAL_GET_MESSAGE = None
_INSTALLED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _acquire_writer_authority_before_runtime_repairs() -> None:
    """Acquire the reviewed canonical lease before sitecustomize starts monitors.

    The Docker ``.pth`` hook remains defense in depth.  This source-level path
    also works when a platform starts directly from repository source or omits
    image-installed ``.pth`` files.  The delegated guard remains fail-closed and
    reuses the same singleton later consumed by ``bot_main``.
    """

    live = (
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )
    if not live:
        return

    previous_force = os.environ.get("NIJA_PREBOT_WRITER_AUTHORITY_FORCE")
    os.environ["NIJA_PREBOT_WRITER_AUTHORITY_FORCE"] = "1"
    try:
        import prebot_writer_authority_fail_closed as authority

        runtime = authority.install()
        if runtime is None or os.environ.get("NIJA_PREBOT_WRITER_AUTHORITY_READY") != "1":
            raise RuntimeError("canonical pre-bot writer authority did not become ready")
        logging.getLogger("nija.logging_format_guard").critical(
            "SITECUSTOMIZE_PREBOT_WRITER_AUTHORITY_READY marker=20260710ad "
            "canonical_singleton=true"
        )
        print(
            "[NIJA-PRINT] SITECUSTOMIZE_PREBOT_WRITER_AUTHORITY_READY "
            "marker=20260710ad canonical_singleton=true",
            flush=True,
        )
    finally:
        if previous_force is None:
            os.environ.pop("NIJA_PREBOT_WRITER_AUTHORITY_FORCE", None)
        else:
            os.environ["NIJA_PREBOT_WRITER_AUTHORITY_FORCE"] = previous_force


# Module execution occurs before sitecustomize invokes install_import_hook().
# Therefore no downstream startup monitor can start without fencing lineage.
_acquire_writer_authority_before_runtime_repairs()


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


def _install_exposure_hard_block_runtime_patch() -> None:
    try:
        try:
            from bot.exposure_hard_block_runtime_patch import install_import_hook
        except ImportError:
            from exposure_hard_block_runtime_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logging.getLogger("nija.logging_format_guard").warning(
            "EXPOSURE_HARD_BLOCK_RUNTIME_INSTALL_REQUESTED marker=20260706g"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "Exposure hard-block runtime patch unavailable: %s",
            exc,
        )


def _install_ohlc_direct_rest_guard() -> None:
    try:
        try:
            from bot.pykrakenapi_ohlc_direct_rest_patch import install_import_hook
        except ImportError:
            from pykrakenapi_ohlc_direct_rest_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logging.getLogger("nija.logging_format_guard").warning(
            "PYKRAKENAPI_OHLC_DIRECT_REST_EARLY_INSTALL_REQUESTED marker=20260708a"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "PyKrakenAPI OHLC direct REST patch unavailable: %s",
            exc,
        )


def _install_seak_stale_halt_recovery() -> None:
    try:
        try:
            from bot.seak_stale_halt_recovery_patch import install_import_hook
        except ImportError:
            from seak_stale_halt_recovery_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logging.getLogger("nija.logging_format_guard").warning(
            "SEAK_STALE_HALT_RECOVERY_EARLY_INSTALL_REQUESTED marker=20260708a"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "SEAK stale halt recovery unavailable: %s",
            exc,
        )


def _install_filesystem_emergency_stop_replay_recovery() -> None:
    try:
        try:
            from bot.filesystem_emergency_stop_replay_recovery_patch import install_import_hook
        except ImportError:
            from filesystem_emergency_stop_replay_recovery_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logging.getLogger("nija.logging_format_guard").warning(
            "FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_EARLY_INSTALL_REQUESTED marker=20260708b"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "Filesystem emergency-stop replay recovery unavailable: %s",
            exc,
        )


def _install_spot_long_signal_side_alignment() -> None:
    try:
        try:
            from bot.spot_long_signal_side_alignment_patch import install_import_hook
        except ImportError:
            from spot_long_signal_side_alignment_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logging.getLogger("nija.logging_format_guard").warning(
            "SPOT_LONG_SIGNAL_SIDE_ALIGNMENT_EARLY_INSTALL_REQUESTED marker=20260708c"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "Spot long signal side-alignment patch unavailable: %s",
            exc,
        )


def _install_direct_broker_venue_cash_gate() -> None:
    try:
        try:
            from bot.direct_broker_venue_cash_hard_gate_patch import install_import_hook
        except ImportError:
            from direct_broker_venue_cash_hard_gate_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logging.getLogger("nija.logging_format_guard").warning(
            "DIRECT_BROKER_VENUE_CASH_HARD_GATE_EARLY_INSTALL_REQUESTED marker=20260708a"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "Direct broker venue cash hard gate unavailable: %s",
            exc,
        )


def _install_ai_hub_terminal_rejection_gate() -> None:
    try:
        try:
            from bot.ai_hub_terminal_rejection_hard_gate_patch import install_import_hook
        except ImportError:
            from ai_hub_terminal_rejection_hard_gate_patch import install_import_hook  # type: ignore[import]
        install_import_hook()
        logging.getLogger("nija.logging_format_guard").warning(
            "AI_HUB_TERMINAL_REJECTION_HARD_GATE_EARLY_INSTALL_REQUESTED marker=20260708a"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "AI Hub terminal rejection hard gate unavailable: %s",
            exc,
        )


def _install_live_capital_and_route_guards() -> None:
    try:
        try:
            from bot.capital_authority_live_total_patch import install_import_hook as capital_install
        except ImportError:
            from capital_authority_live_total_patch import install_import_hook as capital_install  # type: ignore[import]
        capital_install()
        logging.getLogger("nija.logging_format_guard").warning(
            "CAPITAL_AUTHORITY_LIVE_TOTAL_EARLY_INSTALL_REQUESTED marker=20260707b"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "Capital authority live-total guard unavailable: %s",
            exc,
        )

    try:
        try:
            from bot.execution_route_integrity_import_guard_patch import install_import_hook as route_install
        except ImportError:
            from execution_route_integrity_import_guard_patch import install_import_hook as route_install  # type: ignore[import]
        route_install()
        logging.getLogger("nija.logging_format_guard").warning(
            "EXECUTION_ROUTE_INTEGRITY_IMPORT_GUARD_EARLY_INSTALL_REQUESTED marker=20260707b"
        )
    except Exception as exc:
        logging.getLogger("nija.logging_format_guard").warning(
            "Execution route integrity import guard unavailable: %s",
            exc,
        )


def install() -> None:
    global _ORIGINAL_GET_MESSAGE, _INSTALLED
    if _INSTALLED:
        _install_ohlc_direct_rest_guard()
        _install_seak_stale_halt_recovery()
        _install_filesystem_emergency_stop_replay_recovery()
        _install_spot_long_signal_side_alignment()
        _install_direct_broker_venue_cash_gate()
        _install_ai_hub_terminal_rejection_gate()
        _install_live_capital_and_route_guards()
        _install_sector_tier_hydration_repair()
        _install_exposure_hard_block_runtime_patch()
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
    _install_ohlc_direct_rest_guard()
    _install_seak_stale_halt_recovery()
    _install_filesystem_emergency_stop_replay_recovery()
    _install_spot_long_signal_side_alignment()
    _install_direct_broker_venue_cash_gate()
    _install_ai_hub_terminal_rejection_gate()
    _install_live_capital_and_route_guards()
    _install_sector_tier_hydration_repair()
    _install_exposure_hard_block_runtime_patch()


def install_import_hook() -> None:
    install()
