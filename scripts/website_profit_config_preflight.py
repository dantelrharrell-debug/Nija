"""Operator-only, value-free profit-report configuration diagnostic.

Run within the authorized billing process's configuration context. It does
not read an evidence file, call a provider, write anything, or certify profit.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path

_PERIOD = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_MAX_EVIDENCE_BYTES = 8 * 1024 * 1024


def _key_state(value: str) -> str:
    if not value:
        return "missing"
    if not value.isascii():
        return "non_ascii"
    if len(value) < 32:
        return "below_minimum"
    return "present"


def _evidence_metadata(folder: str, period: str) -> tuple[str, str]:
    if not folder:
        return "missing", "not_checked"
    try:
        root = Path(folder).expanduser().resolve(strict=True)
        if not root.is_dir():
            return "not_directory", "not_checked"
    except FileNotFoundError:
        return "not_found", "not_checked"
    except (OSError, RuntimeError, ValueError):
        return "not_accessible", "not_checked"

    path = root / (period + ".json")
    try:
        item = path.lstat()
        if not stat.S_ISREG(item.st_mode):
            return "present", "not_regular_file"
        if item.st_size > _MAX_EVIDENCE_BYTES:
            return "present", "above_size_limit"
        if not os.access(path, os.R_OK):
            return "present", "not_readable"
        return "present", "readable_metadata_only"
    except FileNotFoundError:
        return "present", "not_found"
    except (OSError, RuntimeError, ValueError):
        return "present", "not_accessible"


def preflight(environ: Mapping[str, str], period: str) -> dict[str, str | bool]:
    """Return fixed statuses only, without printing values, paths or evidence."""
    if not _PERIOD.fullmatch(period):
        raise ValueError("period must be YYYY-MM")
    token = environ.get("NIJA_PROFIT_DASHBOARD_TOKEN", "").strip()
    signing = environ.get("NIJA_PROFIT_EVIDENCE_HMAC_KEY", "").strip()
    folder = environ.get("NIJA_PROFIT_EVIDENCE_DIR", "").strip()
    token_state, signing_state = _key_state(token), _key_state(signing)
    distinct = "not_checked"
    if token_state == signing_state == "present":
        distinct = "matching" if hmac.compare_digest(token, signing) else "distinct"
    directory, evidence = _evidence_metadata(folder, period)
    return {
        "dashboard_token": token_state,
        "evidence_signing_key": signing_state,
        "key_separation": distinct,
        "evidence_directory": directory,
        "period_file": evidence,
        "financial_certification": False,
    }


def main() -> None:
    """Print one value-free JSON object for an explicitly named accounting month."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", required=True, metavar="YYYY-MM")
    args = parser.parse_args()
    if not _PERIOD.fullmatch(args.period):
        parser.error("--period must be YYYY-MM")
    print(json.dumps(preflight(os.environ, args.period), sort_keys=True))


if __name__ == "__main__":
    main()
