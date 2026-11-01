"""Fail-closed, read-only database identity check for NIJA's Render billing staging.

The service must never initialize its mutable billing tables against the wrong
PostgreSQL database. The guard runs before billing_service.create_app and
logs no connection string, username, password, account, or customer data.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_STAGING_RENDER_SERVICE_ID = "srv-dasmtjfpn0mc73948r10"
_STAGING_DATABASE_NAME = "nija_billing_staging_db"
_STAGING_DATABASE_HOST = "dpg-dbhtsmqjnfac73cbblmg-a"
_logger = logging.getLogger("nija.billing.staging.database")


def verify_staging_database_binding(
    database_url: str,
    *,
    service_id: str | None = None,
    engine_factory: Callable | None = None,
) -> bool:
    """Check target DSN AND actual database before staging initializes tables.

    Return False without connecting outside the exact Render staging service.
    Fail closed on configuration, connection, or identity mismatches; this
    check must not create, modify, or read billing/customer rows.
    """
    render_id = os.getenv("RENDER_SERVICE_ID", "").strip() if service_id is None else service_id
    if render_id != _STAGING_RENDER_SERVICE_ID:
        return False

    try:
        url = make_url(database_url)
    except (ValueError, ArgumentError):
        raise RuntimeError("billing_staging_database_url_invalid") from None

    host = (url.host or "").lower()
    if (
        url.get_backend_name() != "postgresql"
        or url.database != _STAGING_DATABASE_NAME
        or not (host == _STAGING_DATABASE_HOST or host.startswith(_STAGING_DATABASE_HOST + "."))
    ):
        raise RuntimeError("billing_staging_database_target_mismatch")

    engine = None
    try:
        engine = (engine_factory or create_engine)(
            database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
        )
        with engine.connect() as connection:
            actual_name = connection.execute(text("SELECT current_database()")).scalar_one()
    except Exception:
        # Suppress driver exceptions, which can contain connection metadata.
        raise RuntimeError("billing_staging_database_identity_probe_failed") from None
    finally:
        if engine is not None:
            engine.dispose()

    if actual_name != _STAGING_DATABASE_NAME:
        raise RuntimeError("billing_staging_database_identity_mismatch")

    _logger.info(
        "Billing staging database isolation VERIFIED: database_name=%s, resource_id_prefix=%s",
        _STAGING_DATABASE_NAME, _STAGING_DATABASE_HOST,
    )
    return True
