"""Read-only operational preflight for NIJA member broker credential onboarding.

Never toggles intake or prints environment variable values. Run against the
existing isolated member broker API deployment to locate missing prerequisites.
"""
from __future__ import annotations

import importlib
import os
import sys

REQUIRED = (
    "NIJA_POCKETBASE_URL",
    "NIJA_BROKER_VAULT_KEY_B64",
    "NIJA_VAULT_BILLING_READONLY_URL",
    "NIJA_VAULT_STRIPE_READONLY_KEY",
    "NIJA_VAULT_FOUNDING_PRICE_ID",
    "NIJA_VAULT_FOUNDING_PRODUCT_ID",
)
REVIEW_FLAGS = (
    "NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED",
    "NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED",
)
MODULES = ("flask", "requests", "cryptography", "stripe", "sqlalchemy")


def preflight(environ=None, import_module=None):
    env = os.environ if environ is None else environ
    loader = importlib.import_module if import_module is None else import_module
    missing = [key for key in REQUIRED if not env.get(key, "").strip()]
    unchecked = [key for key in REVIEW_FLAGS if env.get(key) != "true"]
    unavailable = []
    for name in MODULES:
        try:
            loader(name)
        except ImportError:
            unavailable.append(name)
    intake_enabled = env.get("NIJA_VAULT_INTAKE_ENABLED") == "true"
    return {
        "ready_for_review": not (missing or unchecked or unavailable),
        "intake_enabled": intake_enabled,
        "missing_variable_names": missing,
        "unverified_gate_names": unchecked,
        "missing_dependency_names": unavailable,
        "note": "Configuration presence is not proof of vault ACL, identity mapping, billing entitlement or broker connectivity.",
    }


if __name__ == "__main__":
    import json
    result = preflight()
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result["ready_for_review"] else 2)
