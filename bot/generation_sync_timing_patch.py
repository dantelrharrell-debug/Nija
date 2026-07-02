from __future__ import annotations

import importlib
import logging
import os

logger = logging.getLogger("nija.generation_sync_timing_patch")


def install_import_hook() -> None:
    os.environ["NIJA_GENERATION_MISMATCH_RECOVERY_COOLDOWN_S"] = "0"
    for name in ("bot.writer_generation_tracker", "writer_generation_tracker"):
        try:
            module = importlib.import_module(name)
            old = getattr(module, "_SYNC_RECOVERY_COOLDOWN_S", None)
            setattr(module, "_SYNC_RECOVERY_COOLDOWN_S", 0.0)
            logger.warning("GENERATION_SYNC_TIMING_PATCH_APPLIED module=%s old=%s new=0.0", name, old)
            print("[NIJA-PRINT] GENERATION_SYNC_TIMING_PATCH_APPLIED | cooldown_s=0", flush=True)
        except Exception as exc:
            logger.debug("generation sync timing patch deferred for %s: %s", name, exc)
