"""Startup-time safety normalisation for live runtime flags."""

from __future__ import annotations

from collections.abc import MutableMapping

TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled"}
LIVE_BYPASS_FLAGS = (
    "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK",
    "NIJA_DISABLE_WRITER_LOCK",
    "NIJA_FORCE_ACTIVATION",
    "NIJA_SKIP_STARTUP_PHASE_GATE",
)


def env_truthy(value: str | None) -> bool:
    """Return ``True`` when *value* represents an enabled environment flag."""

    return str(value or "").strip().lower() in TRUTHY_ENV_VALUES


def live_mode_enabled(env: MutableMapping[str, str]) -> bool:
    """Return ``True`` when the runtime should be treated as live mode."""

    return not env_truthy(env.get("DRY_RUN_MODE")) and not env_truthy(env.get("PAPER_MODE"))


def normalize_runtime_startup_env(env: MutableMapping[str, str]) -> list[str]:
    """Fail closed on test/unsafe live-mode flags and restore default HF scalp mode."""

    notes: list[str] = []
    if not live_mode_enabled(env):
        return notes

    bypass_confirmed = env_truthy(env.get("NIJA_CONFIRM_BYPASS_RISKS"))

    if not bypass_confirmed:
        for flag in LIVE_BYPASS_FLAGS:
            if env_truthy(env.get(flag)):
                env[flag] = "0" if "LOCK" in flag else "false"
                notes.append(f"cleared:{flag}")

    hf_flip_mode = env_truthy(env.get("HF_FLIP_MODE"))
    hf_scalp_mode = env_truthy(env.get("HF_SCALP_MODE"))
    if not hf_flip_mode and not hf_scalp_mode:
        env["HF_SCALP_MODE"] = "1"
        notes.append("enabled:HF_SCALP_MODE")

    env.setdefault("HF_SCALPING_MODE", env.get("HF_SCALP_MODE", "1"))
    return notes
