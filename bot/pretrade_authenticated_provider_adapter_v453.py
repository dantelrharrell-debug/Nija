"""Read-only adapter for independently implemented authenticated evidence providers.

Providers are explicitly injected by the trusted application composition root.
This module does NOT infer truth from runtime flags, cache freshness, or a
self-declared source string, and is NOT connected to trading admission.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.pretrade_attestation_validation_v452 import REQUIRED, evaluate_pretrade_certificate

EvidenceProvider = Callable[[], Mapping[str, Any]]


def collect_independent_pretrade_evidence(
    providers: Mapping[str, EvidenceProvider],
    *,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Call separately registered read-only producers; reject absent or faulty ones.

    Providers must implement their own authenticated account-specific readbacks.
    Merely returning verified=True is not independent certification.
    """
    observed: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key in REQUIRED:
        provider = providers.get(key) if isinstance(providers, Mapping) else None
        if not callable(provider):
            errors[key] = "independent_provider_missing"
            continue
        try:
            row = provider()
            if not isinstance(row, Mapping):
                errors[key] = "provider_result_invalid"
                continue
            # Preserve the provider's evidence untouched for validation.
            observed[key] = dict(row)
        except Exception as exc:
            errors[key] = "provider_exception:" + type(exc).__name__
    certificate = evaluate_pretrade_certificate(observed, now_epoch=now_epoch)
    return {
        "certificate": certificate,
        "provider_errors": errors,
        "observations": observed,
        "activation_allowed": False,
        "read_only": True,
    }
