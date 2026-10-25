"""Auxiliary authentication must share the runtime nonce stream and lock."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import threading
import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import pytest

import kraken_private_nonce as authority
import member_broker_kraken_readonly as member
import validate_broker_credentials as validator

SECRET = base64.b64encode(b"fixture-only-secret").decode()


def test_member_and_validator_share_per_key_sequence_and_wire_order():
    lock = threading.RLock()
    counters = {}
    observed = []
    active = threading.local()

    @contextmanager
    def tracked_lock():
        with lock:
            active.held = True
            try:
                yield
            finally:
                active.held = False

    def allocate(key_id):
        assert active.held
        counters[key_id] = counters.get(key_id, 1_790_000_000_000) + 1
        # Deliberately allow competing threads to run before transport.
        time.sleep(0.001)
        return counters[key_id]

    manager = Mock(get_nonce=Mock(side_effect=allocate))

    def load(key):
        key_id = hashlib.sha256(key.encode()).hexdigest()[:16]
        return manager, key_id, tracked_lock()

    def post(url, **kwargs):
        assert active.held
        observed.append(int(kwargs["data"]["nonce"]))
        return Mock(status_code=200, json=lambda: {"error": [], "result": {}})

    def urlopen(req, **kwargs):
        assert active.held
        observed.append(int(parse_qs(req.data.decode())["nonce"][0]))
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"error": [], "result": {}}).encode()
        return response

    def verify(index):
        if index % 2:
            return member.verify_kraken_readonly("shared-key", SECRET)
        return validator._kraken_private_request("Balance", "shared-key", SECRET)

    with patch.object(authority, "_load_authority", side_effect=load), \
            patch.object(member.requests, "post", side_effect=post), \
            patch.object(validator.urllib.request, "urlopen", side_effect=urlopen):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(verify, range(24)))

    assert observed == list(range(1_790_000_000_001, 1_790_000_000_025))
    assert len(counters) == 1


@pytest.mark.parametrize("error", [RuntimeError("blocked"), ImportError("unavailable")])
def test_missing_authority_never_sends_either_request(error):
    with patch.object(authority, "_load_authority", side_effect=error), \
            patch.object(member.requests, "post") as post, \
            patch.object(validator.urllib.request, "urlopen") as urlopen:
        with pytest.raises(member.KrakenVerificationError):
            member.verify_kraken_readonly("shared-key", SECRET)
        with pytest.raises(type(error)):
            validator._kraken_private_request("Balance", "shared-key", SECRET)
        post.assert_not_called()
        urlopen.assert_not_called()


@pytest.mark.parametrize("value", [True, -1, 0, 2**64, "123"])
def test_invalid_authority_nonce_fails_before_transport(value):
    with patch.object(authority, "_load_authority", return_value=(Mock(get_nonce=lambda key: value),
                                                               "key-id", threading.RLock())), \
            patch.object(member.requests, "post") as post:
        with pytest.raises(member.KrakenVerificationError):
            member.verify_kraken_readonly("shared-key", SECRET)
        post.assert_not_called()


def test_validator_rejects_nonce_override_before_allocating():
    with patch.object(authority, "_load_authority") as load:
        with pytest.raises(ValueError, match="Caller-supplied"):
            validator._kraken_private_request("Balance", "shared-key", SECRET, {"nonce": 1})
        load.assert_not_called()


def test_live_member_transport_rejects_explicit_nonce():
    with patch.object(member.requests, "post") as post:
        with pytest.raises(member.KrakenVerificationError):
            member.verify_kraken_readonly("shared-key", SECRET, nonce=123)
        post.assert_not_called()


def test_lock_released_after_transport_failure():
    lock = threading.Lock()
    with patch.object(authority, "_load_authority", return_value=(Mock(get_nonce=lambda key: 123), "key-id", lock)), \
            patch.object(member.requests, "post", side_effect=member.requests.Timeout("timeout")):
        with pytest.raises(member.KrakenVerificationError):
            member.verify_kraken_readonly("shared-key", SECRET)
    assert lock.acquire(blocking=False)
    lock.release()
