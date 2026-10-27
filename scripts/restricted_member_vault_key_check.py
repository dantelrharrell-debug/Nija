"""Restricted, offline, read-only AES-GCM custody check.

Run only inside an authorized backend session with a securely provisioned
single-record fixture. Never provide keys or ciphertext as command arguments.
No PocketBase calls, writes, trading operations, or credential output.
"""
from __future__ import annotations

import json
import os
import sys

from member_broker_vault import BrokerVault, VaultError


def main() -> int:
    try:
        path = os.environ["NIJA_VAULT_CHECK_RECORD_PATH"]
        if not os.path.isfile(path) or os.path.getsize(path) > 16384:
            raise ValueError("Invalid fixture")
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        if not isinstance(record, dict) or set(record) != {
            "user_id", "broker", "environment", "ciphertext"
        }:
            raise ValueError("Invalid fixture")
        if any(not isinstance(value, str) or not value for value in record.values()):
            raise ValueError("Invalid fixture")
        vault = BrokerVault.from_environment(lambda _member: False)
        credentials = vault.decrypt(
            record["user_id"], record["broker"],
            record["environment"], record["ciphertext"]
        )
        passed = bool(credentials) and all(
            isinstance(k, str) and isinstance(v, str) and bool(v)
            for k, v in credentials.items()
        )
        del credentials
    except (KeyError, ValueError, TypeError, OSError, VaultError, json.JSONDecodeError):
        passed = False
    except Exception:
        passed = False
    sys.stdout.write("PASS\n" if passed else "FAIL\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
