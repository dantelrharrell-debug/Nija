"""
Kraken error taxonomy and retry policy mapping.

This module converts raw Kraken API/broker error strings into a small,
authoritative contract consumed by the execution state controller and execution
result objects.  The classifier is intentionally conservative: terminal account
configuration problems outrank retryable transport/order-flow errors so live
trading stops instead of repeatedly submitting orders under a bad key,
permission set, or funding state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import re
from typing import Iterable, Pattern

logger = logging.getLogger("nija.kraken_error_taxonomy")


class KrakenErrorCategory(str, Enum):
    """Canonical Kraken error buckets used by trade-admission controls."""

    AUTH = "AUTH"
    PERMISSION = "PERMISSION"
    FUNDS = "FUNDS"
    ORDER = "ORDER"
    NONCE = "NONCE"
    RATE_LIMIT = "RATE_LIMIT"
    SERVICE = "SERVICE"
    NETWORK = "NETWORK"
    UNKNOWN = "UNKNOWN"


class KrakenRetryPolicy(str, Enum):
    """Execution-controller action for a classified Kraken error."""

    STOP = "STOP"
    CONFIG_FAIL = "CONFIG_FAIL"
    RETRY = "RETRY"
    BACKOFF = "BACKOFF"


@dataclass(frozen=True)
class KrakenErrorTaxonomy:
    """Structured classification returned for every Kraken error string."""

    category: KrakenErrorCategory
    policy: KrakenRetryPolicy
    canonical_code: str
    retry_delay_s: float
    max_retries: int
    remediation: str
    raw_error: str = ""


@dataclass(frozen=True)
class _Rule:
    category: KrakenErrorCategory
    policy: KrakenRetryPolicy
    canonical_code: str
    retry_delay_s: float
    max_retries: int
    remediation: str
    patterns: tuple[Pattern[str], ...]


_ESC_PRIORITY = {
    KrakenErrorCategory.AUTH: 0,
    KrakenErrorCategory.PERMISSION: 1,
    KrakenErrorCategory.FUNDS: 2,
    KrakenErrorCategory.ORDER: 3,
    KrakenErrorCategory.NONCE: 4,
    KrakenErrorCategory.RATE_LIMIT: 5,
    KrakenErrorCategory.SERVICE: 6,
    KrakenErrorCategory.NETWORK: 7,
    KrakenErrorCategory.UNKNOWN: 99,
}


def _compile(patterns: Iterable[str]) -> tuple[Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


_RULES: tuple[_Rule, ...] = (
    _Rule(
        category=KrakenErrorCategory.AUTH,
        policy=KrakenRetryPolicy.STOP,
        canonical_code="KRAKEN_AUTH_FAILURE",
        retry_delay_s=0.0,
        max_retries=0,
        remediation="Verify Kraken API key, secret, account lock state, and signature generation.",
        patterns=_compile((
            r"\beauth\s*:\s*(invalid\s+key|invalid\s+signature|locked|failed)",
            r"\bauth(?:entication)?\b.*\b(invalid|failed|locked)\b",
        )),
    ),
    _Rule(
        category=KrakenErrorCategory.PERMISSION,
        policy=KrakenRetryPolicy.CONFIG_FAIL,
        canonical_code="KRAKEN_PERMISSION_DENIED",
        retry_delay_s=0.0,
        max_retries=0,
        remediation="Enable the required Kraken API permissions/features before submitting live orders.",
        patterns=_compile((
            r"\begeneral\s*:\s*permission\s+denied",
            r"\beapi\s*:\s*invalid\s+permission",
            r"\binsufficient\s+permission\b",
            r"\beapi\s*:\s*feature\s+disabled",
            r"\bpermission\s+denied\b",
        )),
    ),
    _Rule(
        category=KrakenErrorCategory.FUNDS,
        policy=KrakenRetryPolicy.STOP,
        canonical_code="EXCHANGE_INSUFFICIENT_FUNDS",
        retry_delay_s=0.0,
        max_retries=0,
        remediation="Hydrate or rebalance quote currency before attempting new entries, or route the symbol to a broker with available quote cash.",
        patterns=_compile((
            r"\beorder\s*:\s*insufficient\s+funds",
            r"\binsufficient\s+(funds|balance|margin)\b",
            r"\bavailable\s+(usd|usdt|usdc)\s+balance\s+is\s+insufficient\b",
            r"\ball\s+operations\s+failed\b.*\binsufficient\b",
            r"\bsCode['\"]?\s*[:=]\s*['\"]?51008\b",
            r"\b51008\b.*\binsufficient\b",
        )),
    ),
    _Rule(
        category=KrakenErrorCategory.ORDER,
        policy=KrakenRetryPolicy.STOP,
        canonical_code="KRAKEN_ORDER_REJECTED",
        retry_delay_s=0.0,
        max_retries=0,
        remediation="Adjust order size, symbol, price, or exchange-specific order constraints.",
        patterns=_compile((
            r"\beorder\s*:\s*order\s+minimum\s+not\s+met",
            r"\border\s+minimum\s+not\s+met\b",
            r"\beorder\s*:\s*(invalid|cannot|orders?)",
        )),
    ),
    _Rule(
        category=KrakenErrorCategory.NONCE,
        policy=KrakenRetryPolicy.RETRY,
        canonical_code="KRAKEN_INVALID_NONCE",
        retry_delay_s=1.0,
        max_retries=3,
        remediation="Refresh nonce lease/state and retry with a monotonic nonce.",
        patterns=_compile((
            r"\beapi\s*:\s*invalid\s+nonce",
            r"\bnonce\b.*\b(window|invalid|out\s+of\s+window)\b",
        )),
    ),
    _Rule(
        category=KrakenErrorCategory.RATE_LIMIT,
        policy=KrakenRetryPolicy.BACKOFF,
        canonical_code="KRAKEN_RATE_LIMIT",
        retry_delay_s=5.0,
        max_retries=4,
        remediation="Back off Kraken requests and retry after the rate-limit window clears.",
        patterns=_compile((
            r"\b(?:eapi|eorder)\s*:\s*rate\s+limit\s+exceeded",
            r"\bhttp\s*429\b",
            r"\btoo\s+many\s+requests\b",
            r"\brate\s+limit\b",
        )),
    ),
    _Rule(
        category=KrakenErrorCategory.SERVICE,
        policy=KrakenRetryPolicy.BACKOFF,
        canonical_code="KRAKEN_SERVICE_UNAVAILABLE",
        retry_delay_s=10.0,
        max_retries=3,
        remediation="Retry after Kraken service recovers.",
        patterns=_compile((
            r"\beservice\s*:\s*unavailable",
            r"\bservice\s+unavailable\b",
            r"\bmaintenance\b",
        )),
    ),
    _Rule(
        category=KrakenErrorCategory.NETWORK,
        policy=KrakenRetryPolicy.RETRY,
        canonical_code="KRAKEN_NETWORK_ERROR",
        retry_delay_s=2.0,
        max_retries=3,
        remediation="Retry after transient network/connectivity failure.",
        patterns=_compile((
            r"\bconnection\s+timeout\b",
            r"\btimed?\s*out\b",
            r"\bnetwork\b",
            r"\bconnection\s+(reset|refused|aborted)\b",
        )),
    ),
)

_UNKNOWN = KrakenErrorTaxonomy(
    category=KrakenErrorCategory.UNKNOWN,
    policy=KrakenRetryPolicy.STOP,
    canonical_code="KRAKEN_UNKNOWN_ERROR",
    retry_delay_s=0.0,
    max_retries=0,
    remediation="Inspect the raw exchange error and add a taxonomy rule if it is actionable.",
    raw_error="",
)


def classify_kraken_error(error_text: object) -> KrakenErrorTaxonomy:
    """Classify *error_text* into a deterministic exchange taxonomy record.

    Historical callers still use this function name even for non-Kraken broker
    errors. Keep the public API stable, but classify cross-exchange insufficient
    funds responses such as OKX code 51008 so they are not reported as unknown.
    """

    raw = "" if error_text is None else str(error_text)
    text = raw.strip()
    if not text:
        logger.warning("KRAKEN_RAW_ERROR_EMPTY_BEFORE_CLASSIFICATION raw=%r", error_text)
        return _UNKNOWN

    matches: list[_Rule] = []
    for rule in _RULES:
        if any(pattern.search(text) for pattern in rule.patterns):
            matches.append(rule)

    if not matches:
        logger.error("KRAKEN_RAW_ERROR_UNCLASSIFIED raw=%r", raw)
        return KrakenErrorTaxonomy(**{**_UNKNOWN.__dict__, "raw_error": raw})

    selected = min(matches, key=lambda rule: _ESC_PRIORITY.get(rule.category, 99))
    logger.warning(
        "KRAKEN_RAW_ERROR_CLASSIFIED code=%s category=%s policy=%s raw=%r",
        selected.canonical_code,
        selected.category.value,
        selected.policy.value,
        raw,
    )
    return KrakenErrorTaxonomy(
        category=selected.category,
        policy=selected.policy,
        canonical_code=selected.canonical_code,
        retry_delay_s=selected.retry_delay_s,
        max_retries=selected.max_retries,
        remediation=selected.remediation,
        raw_error=raw,
    )


def get_retry_policy(error_text: object) -> KrakenRetryPolicy:
    """Return only the retry policy for callers that do not need full detail."""

    return classify_kraken_error(error_text).policy


def is_fatal_auth_error(error_text: object) -> bool:
    return classify_kraken_error(error_text).category is KrakenErrorCategory.AUTH


def is_nonce_error(error_text: object) -> bool:
    return classify_kraken_error(error_text).category is KrakenErrorCategory.NONCE


def is_rate_limit_error(error_text: object) -> bool:
    return classify_kraken_error(error_text).category is KrakenErrorCategory.RATE_LIMIT


def is_permission_error(error_text: object) -> bool:
    return classify_kraken_error(error_text).category is KrakenErrorCategory.PERMISSION


__all__ = [
    "KrakenErrorCategory",
    "KrakenRetryPolicy",
    "KrakenErrorTaxonomy",
    "classify_kraken_error",
    "get_retry_policy",
    "is_fatal_auth_error",
    "is_nonce_error",
    "is_rate_limit_error",
    "is_permission_error",
]
