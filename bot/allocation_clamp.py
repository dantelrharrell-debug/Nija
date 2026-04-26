from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger("nija.allocation_clamp")


@dataclass
class AllocationClampResult:
    requested_usd: float
    baseline_usd: float
    clamped_usd: float
    min_allowed_usd: float
    max_allowed_usd: float
    was_clamped: bool
    reason: str


class AllocationClamp:
    """Clamp allocation adjustments to safe hard bounds."""

    def __init__(self, min_multiplier: float = 0.5, max_multiplier: float = 1.5) -> None:
        self.min_multiplier = float(min_multiplier)
        self.max_multiplier = float(max_multiplier)

    def clamp(self, requested_usd: float, baseline_usd: float) -> AllocationClampResult:
        baseline = float(baseline_usd if baseline_usd > 0 else requested_usd)
        requested = float(requested_usd)
        min_allowed = baseline * self.min_multiplier
        max_allowed = baseline * self.max_multiplier
        clamped = max(min_allowed, min(requested, max_allowed))
        was_clamped = abs(clamped - requested) > 1e-9

        if requested < min_allowed:
            reason = f"below minimum {self.min_multiplier:.2f}x"
        elif requested > max_allowed:
            reason = f"above maximum {self.max_multiplier:.2f}x"
        else:
            reason = "within bounds"

        if was_clamped:
            logger.info(
                "AllocationClamp: requested=$%.2f baseline=$%.2f -> $%.2f (%s)",
                requested,
                baseline,
                clamped,
                reason,
            )

        return AllocationClampResult(
            requested_usd=requested,
            baseline_usd=baseline,
            clamped_usd=clamped,
            min_allowed_usd=min_allowed,
            max_allowed_usd=max_allowed,
            was_clamped=was_clamped,
            reason=reason,
        )


_instance: AllocationClamp | None = None
_lock = threading.Lock()


def get_allocation_clamp() -> AllocationClamp:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AllocationClamp()
    return _instance