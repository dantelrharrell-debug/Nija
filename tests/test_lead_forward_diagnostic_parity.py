"""Read-only diagnostic URL classifications must match the live forwarder.

All destinations are synthetic. These tests do not open sockets, access actual
customer records, or authorize forwarding, publishing, payment, or trading.
"""
import json
import tempfile
from pathlib import Path

import pytest

from render_lead_intake import _validated_forward_url
from scripts.nija_lead_storage_preflight import (
    _approved_zapier_catch_hook as storage_approved,
    inspect as storage_inspect,
)
from scripts.nija_lead_delivery_reconciliation_readonly import (
    _approved_zapier_catch_hook as reconciliation_approved,
    inspect as reconciliation_inspect,
)


VALID = "https://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/"

DESTINATIONS = [
    (VALID, True),
    (VALID[:-1], True),
    ("https://hooks.zapier.com/hooks/catch/1/a", True),
    ("https://HOOKS.ZAPIER.COM/hooks/catch/123456/syntheticQA_token/", True),
    ("", False),
    ("http://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/", False),
    ("https://hooks.zapier.com.evil.example/hooks/catch/123456/syntheticQA_token/", False),
    ("https://hooks.zapier.com@evil.example/hooks/catch/123456/syntheticQA_token/", False),
    ("https://" + "user" + ":" + "pass" + "@hooks.zapier.com/hooks/catch/123456/syntheticQA_token/", False),
    ("https://hooks.zapier.com:443/hooks/catch/123456/syntheticQA_token/", False),
    ("https://hooks.zapier.com:bad/hooks/catch/123456/syntheticQA_token/", False),
    ("https://hooks.zapier.com/hooks/catch/notnumeric/syntheticQA_token/", False),
    ("https://hooks.zapier.com/hooks/catch/123456/", False),
    ("https://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/extra", False),
    ("https://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/?debug=1", False),
    ("https://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/#fragment", False),
    ("https://hooks.zapier.com/hooks/catch/123456/syntheticQA%2ftoken/", False),
    (" https://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/", False),
    ("https://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/\n", False),
    ("https://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/\x00", False),
]


@pytest.mark.parametrize("destination,expected", DESTINATIONS)
def test_diagnostics_match_production_forwarder(destination, expected):
    try:
        accepted = _validated_forward_url(destination) == destination
    except OSError:
        accepted = False
    assert accepted is expected
    assert storage_approved(destination) is expected
    assert reconciliation_approved(destination) is expected


@pytest.mark.parametrize("destination,expected", [
    (VALID, True),
    ("https://hooks.zapier.com/hooks/catch/any/path", False),
    ("https://evil.example/hooks/catch/123456/syntheticQA_token/", False),
    (VALID + "?secret=syntheticQA_token", False),
    (" " + VALID, False),
])
def test_diagnostic_reports_never_leak_or_mutate(destination, expected):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        disk = root / "data"
        disk.mkdir()
        env = {
            "NIJA_LEAD_DB_PATH": str(disk / "not-present.sqlite3"),
            "NIJA_LEAD_FORWARD_DB_PATH": str(disk / "no-history.sqlite3"),
            "NIJA_LEAD_WEBHOOK_TOKEN": "synthetic-secret",
            "NIJA_LEAD_FORWARD_URL": destination,
        }
        before = list(disk.iterdir())
        a = storage_inspect(environ=env, disk=disk,
                            app_default=root / "app.sqlite3",
                            mount_check=lambda _: True)
        b = reconciliation_inspect(environ=env, disk=disk,
                                   app_default=root / "app.sqlite3",
                                   mount_check=lambda _: True)
        assert a["forwarding_https_configured"] is expected
        assert b["configured_forwarding_https"] is expected
        assert a["forwarding_destination_category"] == (
            "zapier" if expected else "missing_or_invalid")
        assert b["configured_forwarding_category"] == (
            "zapier" if expected else "missing_or_invalid")
        assert a["production_certified"] is False
        assert b["production_pipeline_certified"] is False
        assert list(disk.iterdir()) == before
        public_report = json.dumps([a, b])
        assert "syntheticQA_token" not in public_report
        assert "synthetic-secret" not in public_report
        assert "evil.example" not in public_report
