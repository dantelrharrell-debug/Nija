"""Patch bot_main so canonical broker preparation runs directly on the main thread.

This removes reliance on import-hook wrappers for the safety-critical transition
between verified writer authority and SelfHealingStartup. The patch is idempotent
and fail-closed: if canonical broker preparation fails, startup returns failure
before SelfHealingStartup, capital hydration, or trading can proceed.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_MAIN = ROOT / "bot" / "bot_main.py"
MARKER = "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27"

ANCHOR = '''    try:\n        logger.info("\\n[STEP 1] Self-Healing Bootstrap")\n'''

BLOCK = '''    try:\n        logger.info("\\n[STEP 0.5] Canonical Broker Prebootstrap")\n        try:\n            from bot.canonical_broker_prebootstrap_v22 import (\n                prepare_canonical_broker_runtime,\n            )\n\n            manager = prepare_canonical_broker_runtime()\n            if not bool(getattr(manager, "_fsm_initialized", False)):\n                raise RuntimeError("canonical broker manager FSM is not initialized")\n            logger.critical(\n                "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY "\n                "fsm_initialized=true thread=%s",\n                threading.current_thread().name,\n            )\n            os.environ["NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY"] = "1"\n        except Exception as broker_exc:\n            os.environ["NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY"] = "0"\n            logger.critical(\n                "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_FAILED err=%s:%s "\n                "trading_remains_fail_closed=true",\n                type(broker_exc).__name__,\n                broker_exc,\n                exc_info=True,\n            )\n            return 1\n\n        logger.info("\\n[STEP 1] Self-Healing Bootstrap")\n'''


def patch_text(text: str) -> str:
    if MARKER in text:
        if text.count(MARKER) < 2:
            raise RuntimeError("v27 direct prebootstrap marker is incomplete")
        return text
    if ANCHOR not in text:
        raise RuntimeError("bot_main startup anchor not found")
    patched = text.replace(ANCHOR, BLOCK, 1)
    if MARKER not in patched:
        raise RuntimeError("v27 direct prebootstrap patch was not installed")
    return patched


def main() -> None:
    original = BOT_MAIN.read_text(encoding="utf-8")
    patched = patch_text(original)
    BOT_MAIN.write_text(patched, encoding="utf-8")
    print(
        "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_PATCH_APPLIED "
        "main_thread=true fail_closed=true idempotent=true"
    )


if __name__ == "__main__":
    main()
