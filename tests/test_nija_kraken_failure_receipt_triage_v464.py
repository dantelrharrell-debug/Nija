"""Security/fail-closed synthetic tests for private v464 diagnostic."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

spec = importlib.util.spec_from_file_location(
    "nija_kraken_failure_receipt_triage_v464",
    Path(__file__).with_name("nija_kraken_failure_receipt_triage_v464.py"),
)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)
ID = "b0b11dc2935353944488dc54ee2c76a6"


@pytest.fixture
def files(tmp_path):
    tmp_path.chmod(0o700)
    claim = tmp_path / (ID + ".claimed.json")
    receipt = tmp_path / (ID + ".evidence.json")
    claim.write_text(json.dumps({"request_id": ID, "account_scope": "platform:kraken",
                                 "created_at": 1792750000, "max_pages": 10}))
    receipt.write_text(json.dumps({"request_id": ID, "collection_succeeded": False,
                                   "trading_authorized": False, "error_type": "IncompleteHistory",
                                   "error_code": "page_limit", "error_endpoint": "ClosedOrders",
                                   "requested_pages": 10, "required_pages": 47}))
    claim.chmod(0o600)
    receipt.chmod(0o600)
    return tmp_path, claim, receipt


def test_operator_receipt_redacted_and_no_writes(files):
    root, claim, receipt = files
    before = [claim.read_bytes(), receipt.read_bytes()]
    out = api.inspect_failure(root, ID)
    assert out["required_pages"] == 47
    assert out["requested_pages"] == 10
    assert out["rate_budget_approved"] is False
    assert out["execution_authorized"] is False
    assert out["broker_reads_performed_by_triage"] is False
    assert ID not in json.dumps(out)
    assert [claim.read_bytes(), receipt.read_bytes()] == before


def test_older_receipt_missing_counts_does_not_guess(files):
    root, _, receipt = files
    data = json.loads(receipt.read_text())
    del data["required_pages"]
    del data["requested_pages"]
    receipt.write_text(json.dumps(data))
    assert api.inspect_failure(root, ID)["complete_page_budget_known"] is False


@pytest.mark.parametrize("code", [
    "wrong_scope", "wrong_claim_budget", "world_readable", "symlink",
    "duplicate_key", "extra_receipt_field", "mismatch_id", "success",
    "mismatch_budget", "bool_budget", "nonfinite", "future_schema",
])
def test_untrusted_receipt_denied(files, code):
    root, claim, receipt = files
    a = json.loads(claim.read_text())
    b = json.loads(receipt.read_text())
    if code == "wrong_scope":
        a["account_scope"] = "user:somebody:kraken"
    elif code == "wrong_claim_budget":
        a["max_pages"] = 101
    elif code == "world_readable":
        receipt.chmod(0o644)
    elif code == "symlink":
        src = root / "target.json"
        src.write_bytes(receipt.read_bytes())
        receipt.unlink()
        receipt.symlink_to(src)
    elif code == "duplicate_key":
        receipt.write_text('{"request_id":"' + ID + '","request_id":"' + ID + '"}')
    elif code == "extra_receipt_field":
        b["private_broker_history"] = "must never print"
    elif code == "mismatch_id":
        b["request_id"] = "f" * 32
    elif code == "success":
        b["collection_succeeded"] = True
    elif code == "mismatch_budget":
        b["requested_pages"] = 9
    elif code == "bool_budget":
        b["required_pages"] = True
    elif code == "nonfinite":
        receipt.write_text('{"request_id":"' + ID + '","foo":NaN}')
    elif code == "future_schema":
        b["error_code"] = "secret:abcd"
    if code.startswith("wrong_"):
        claim.write_text(json.dumps(a))
    elif code not in {"symlink", "duplicate_key", "nonfinite", "world_readable"}:
        receipt.write_text(json.dumps(b))
    with pytest.raises(api.TriageFailure):
        api.inspect_failure(root, ID)


def test_refuse_directory_with_open_permissions(files):
    root, *_ = files
    root.chmod(0o755)
    with pytest.raises(api.TriageFailure, match="unsafe_recovery_directory"):
        api.inspect_failure(root, ID)


def test_refuse_invalid_request_id_before_read(files):
    root, *_ = files
    with pytest.raises(api.TriageFailure, match="invalid_request_id"):
        api.inspect_failure(root, "../other")


def test_receipt_cannot_be_missing_after_claim(files):
    root, claim, receipt = files
    receipt.unlink()
    with pytest.raises(api.TriageFailure, match="receipt_missing_or_unreadable"):
        api.inspect_failure(root, ID)


def test_readonly_fields_for_nonpage_failure(files):
    root, _, receipt = files
    data = json.loads(receipt.read_text())
    data["error_code"] = "api_failure"
    data["error_endpoint"] = "Balance"
    data.pop("requested_pages")
    data.pop("required_pages")
    receipt.write_text(json.dumps(data))
    out = api.inspect_failure(root, ID)
    assert out["complete_page_budget_known"] is False
    assert out["failure_endpoint"] == "Balance"