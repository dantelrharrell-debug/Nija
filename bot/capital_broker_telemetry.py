"""Capital broker classification and balance observation telemetry.

This module provides two structured telemetry events required by the NIJA
writer-epoch and capital-provenance audit trail:

1. ``emit_capital_broker_classification`` — emit ``CAPITAL_BROKER_CLASSIFICATION``
   for each broker, distinguishing portfolio equity from execution-eligible
   capital.  Enforces that cached/disconnected Kraken balance can never satisfy
   order-dispatch capital for new Kraken orders.

2. ``emit_capital_balance_observation`` — emit ``CAPITAL_BALANCE_OBSERVATION``
   with an unambiguous ``source`` label so cached or sticky balance data cannot
   be mistaken for a new private HTTP success.

Source taxonomy for CAPITAL_BALANCE_OBSERVATION
------------------------------------------------
``live_http``
    Balance was fetched via a live private HTTP request that completed
    successfully during this refresh cycle.
``fresh_cache``
    Balance comes from a recently-cached result (age below freshness TTL)
    that was stored from a previous live HTTP success.
``sticky_success``
    Balance preserved from a prior successful fetch because the current fetch
    returned zero or raised an exception and the preserve-nonzero policy is
    active (nonce-rebuild cooldown or within preserve_nonzero_ttl_s).
``prior_authenticated_snapshot``
    Balance from an authenticated snapshot that pre-dates the current writer
    generation (writer is now absent/generation 0) — valid for portfolio equity
    accounting only; never valid for order dispatch.

Non-regression contract
-----------------------
* ``may_fund_new_orders=False`` is always set when ``connected=False`` or
  ``execution_eligible=False``.
* ``may_count_in_portfolio_equity`` may be ``True`` for disconnected brokers
  when the observation is still fresh and was previously authenticated.
* This module emits telemetry only — it never changes balances, gates, or
  execution state.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("nija.capital_broker_telemetry")


def emit_capital_broker_classification(
    *,
    broker: str,
    equity_usd: float,
    observation_age_s: float,
    observation_source: str,
    connected: bool,
    execution_eligible: bool,
    may_count_in_portfolio_equity: bool,
    may_fund_new_orders: bool,
) -> None:
    """Emit CAPITAL_BROKER_CLASSIFICATION telemetry event.

    Parameters
    ----------
    broker:
        Broker identifier (e.g. ``"kraken"``, ``"coinbase"``, ``"okx"``).
    equity_usd:
        Most recent balance figure in USD used for portfolio equity accounting.
    observation_age_s:
        Age of the balance observation in seconds.
    observation_source:
        One of ``live_http``, ``fresh_cache``, ``sticky_success``,
        ``prior_authenticated_snapshot``.
    connected:
        Whether the broker is currently connected.
    execution_eligible:
        Whether the broker may receive new order dispatches.
    may_count_in_portfolio_equity:
        Whether this balance may be included in total portfolio equity.
    may_fund_new_orders:
        Whether this balance may be used to fund new orders.  MUST be False
        when ``connected=False`` or ``execution_eligible=False``.
    """
    # Enforce: disconnected or ineligible broker must never fund new orders.
    if (not connected or not execution_eligible) and may_fund_new_orders:
        logger.critical(
            "CAPITAL_BROKER_CLASSIFICATION_CONSTRAINT_VIOLATION "
            "broker=%s connected=%s execution_eligible=%s "
            "may_fund_new_orders=true — overriding to false",
            broker,
            connected,
            execution_eligible,
        )
        may_fund_new_orders = False

    logger.info(
        "CAPITAL_BROKER_CLASSIFICATION "
        "broker=%s "
        "equity_usd=%.4f "
        "observation_age_s=%.3f "
        "observation_source=%s "
        "connected=%s "
        "execution_eligible=%s "
        "may_count_in_portfolio_equity=%s "
        "may_fund_new_orders=%s",
        broker,
        equity_usd,
        observation_age_s,
        observation_source,
        str(connected).lower(),
        str(execution_eligible).lower(),
        str(may_count_in_portfolio_equity).lower(),
        str(may_fund_new_orders).lower(),
    )


def emit_capital_balance_observation(
    *,
    broker: str,
    value: float,
    source: str,
    network_request_started: bool,
    network_response_received: bool,
    writer_generation: int,
    observation_generation: int,
    age_s: float,
) -> None:
    """Emit CAPITAL_BALANCE_OBSERVATION telemetry event.

    Parameters
    ----------
    broker:
        Broker identifier.
    value:
        Balance value in USD.
    source:
        One of ``live_http``, ``fresh_cache``, ``sticky_success``,
        ``prior_authenticated_snapshot``.
    network_request_started:
        Whether a network request was initiated for this observation.
    network_response_received:
        Whether a network response was received (only True for ``live_http``).
    writer_generation:
        The current writer lease generation at the time of the observation.
    observation_generation:
        The writer generation under which the balance was originally fetched.
        May differ from ``writer_generation`` for ``sticky_success`` or
        ``prior_authenticated_snapshot`` sources.
    age_s:
        Age of the observation in seconds.
    """
    # Validate: network_response_received must be False for non-live_http sources.
    if source != "live_http" and network_response_received:
        logger.warning(
            "CAPITAL_BALANCE_OBSERVATION_LABEL_WARNING "
            "broker=%s source=%s network_response_received=true — "
            "only live_http may set network_response_received=true; overriding",
            broker,
            source,
        )
        network_response_received = False

    logger.info(
        "CAPITAL_BALANCE_OBSERVATION "
        "broker=%s "
        "value=%.4f "
        "source=%s "
        "network_request_started=%s "
        "network_response_received=%s "
        "writer_generation=%d "
        "observation_generation=%d "
        "age_s=%.3f",
        broker,
        value,
        source,
        str(network_request_started).lower(),
        str(network_response_received).lower(),
        writer_generation,
        observation_generation,
        age_s,
    )


def classify_observation_source(
    *,
    network_success: bool,
    is_cached: bool,
    is_sticky_preserved: bool,
    observation_generation: int,
    current_writer_generation: int,
) -> str:
    """Return the canonical observation source label.

    Parameters
    ----------
    network_success:
        True when the live HTTP fetch completed successfully this cycle.
    is_cached:
        True when returning a fresh in-memory cache hit (no new HTTP call).
    is_sticky_preserved:
        True when the balance was preserved due to preserve-nonzero policy.
    observation_generation:
        Writer generation under which the observation was originally made.
    current_writer_generation:
        Current writer lease generation.

    Returns
    -------
    str
        One of ``live_http``, ``fresh_cache``, ``sticky_success``,
        ``prior_authenticated_snapshot``.
    """
    if network_success and not is_cached and not is_sticky_preserved:
        return "live_http"
    if is_sticky_preserved:
        if observation_generation > 0 and observation_generation != current_writer_generation:
            return "prior_authenticated_snapshot"
        return "sticky_success"
    if is_cached:
        return "fresh_cache"
    # Fallback: generation mismatch → prior snapshot
    if observation_generation > 0 and observation_generation != current_writer_generation:
        return "prior_authenticated_snapshot"
    return "fresh_cache"


__all__ = [
    "emit_capital_broker_classification",
    "emit_capital_balance_observation",
    "classify_observation_source",
]
