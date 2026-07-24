"""Patch bot_main so canonical broker preparation runs directly on the main thread.

This removes reliance on import-hook wrappers for the safety-critical transition
between verified writer authority and SelfHealingStartup. The patch is idempotent
and fail-closed: if canonical broker preparation fails, startup returns failure
before SelfHealingStartup, capital hydration, or trading can proceed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_MAIN = ROOT / "bot" / "bot_main.py"
MARKER = "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27"
STEP1_PATTERN = re.compile(
    r'(?m)^(?P<indent>[ \t]*)logger\.info\(\s*["\']\\n\[STEP 1\] Self-Healing Bootstrap["\']\s*\)\s*$'
)

BLOCK_TEMPLATE = '''{indent}logger.info("\\n[STEP 0.5] Canonical Broker Prebootstrap")
{indent}try:
{indent}    from bot.canonical_broker_prebootstrap_v22 import (
{indent}        prepare_canonical_broker_runtime,
{indent}    )

{indent}    manager = prepare_canonical_broker_runtime()
{indent}    if not bool(getattr(manager, "_fsm_initialized", False)):
{indent}        raise RuntimeError("canonical broker manager FSM is not initialized")
{indent}    logger.critical(
{indent}        "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY "
{indent}        "fsm_initialized=true thread=%s",
{indent}        threading.current_thread().name,
{indent}    )
{indent}    os.environ["NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY"] = "1"
{indent}except Exception as broker_exc:
{indent}    os.environ["NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY"] = "0"
{indent}    logger.critical(
{indent}        "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_FAILED err=%s:%s "
{indent}        "trading_remains_fail_closed=true",
{indent}        type(broker_exc).__name__,
{indent}        broker_exc,
{indent}        exc_info=True,
{indent}    )
{indent}    return 1

{indent}logger.info("\\n[STEP 1] Self-Healing Bootstrap")'''


def patch_text(text: str) -> str:
    if MARKER in text:
        if "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY" not in text:
            raise RuntimeError("v27 direct prebootstrap marker is incomplete")
        return text

    matches = list(STEP1_PATTERN.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"bot_main STEP 1 structural anchor count invalid: {len(matches)}"
        )

    match = matches[0]
    block = BLOCK_TEMPLATE.format(indent=match.group("indent"))
    patched = text[: match.start()] + block + text[match.end() :]

    if MARKER not in patched:
        raise RuntimeError("v27 direct prebootstrap patch was not installed")
    if patched.count("[STEP 0.5] Canonical Broker Prebootstrap") != 1:
        raise RuntimeError("v27 direct prebootstrap insertion count invalid")
    return patched


def main() -> None:
    original = BOT_MAIN.read_text(encoding="utf-8")
    patched = patch_text(original)
    BOT_MAIN.write_text(patched, encoding="utf-8")
    print(
        "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_PATCH_APPLIED "
        "main_thread=true fail_closed=true structural_anchor=true idempotent=true"
    )


if __name__ == "__main__":
    main()
