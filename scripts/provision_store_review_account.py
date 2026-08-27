#!/usr/bin/env python3
"""Provision a dedicated NIJA store-review account from environment variables.

This helper intentionally does not accept a plaintext password as a command-line
argument because shell history and process listings can expose CLI secrets.

Required environment variables:
  NIJA_REVIEWER_EMAIL
  NIJA_REVIEWER_PASSWORD

Optional:
  NIJA_REVIEWER_USER_ID (default: store-reviewer)
  NIJA_REVIEWER_TIER (default: basic)
  NIJA_USER_DB_PATH (default: users.db)

Never commit reviewer credentials to the repository.
"""

from __future__ import annotations

import os
import sys

from auth.user_database import get_user_database


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    try:
        email = _required("NIJA_REVIEWER_EMAIL")
        password = _required("NIJA_REVIEWER_PASSWORD")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    user_id = os.getenv("NIJA_REVIEWER_USER_ID", "store-reviewer").strip() or "store-reviewer"
    tier = os.getenv("NIJA_REVIEWER_TIER", "basic").strip() or "basic"
    db_path = os.getenv("NIJA_USER_DB_PATH", "users.db").strip() or "users.db"

    if len(password) < 12:
        print("ERROR: NIJA_REVIEWER_PASSWORD must be at least 12 characters.", file=sys.stderr)
        return 2

    db = get_user_database(db_path)
    existing = db.get_user(user_id) or db.get_user_by_email(email)
    if existing:
        print(
            "Reviewer account already exists. Rotate/reset credentials through the approved "
            "account-management path rather than creating a duplicate."
        )
        return 0

    created = db.create_user(
        user_id=user_id,
        email=email,
        password=password,
        subscription_tier=tier,
    )
    if not created:
        print("ERROR: reviewer account creation failed.", file=sys.stderr)
        return 1

    print(f"Reviewer account provisioned: user_id={user_id}, email={email}, tier={tier}")
    print("Do not print, log, or commit the password. Enter credentials only in approved store-review fields.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
