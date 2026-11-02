"""Offline regressions exercising the canonical private-call method without startup."""
import ast
import hashlib
import logging
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from bot import kraken_identity_read_timing as timing
from bot.kraken_authenticated_identity_v480 import (
    KrakenIdentityDenied, make_kraken_account_identity_provider,
)


from bot.kraken_authenticated_key_info_v477 import (
    KeyInfoEvidenceDenied, REQUIRED_READ_PERMISSIONS, make_kraken_key_permission_provider,
)


class Clock:
    def __init__(self):
        self.wall = 1000.0
        self.mono = 1000.0

    def time(self):
        return self.wall

    def sleep(self, seconds):
        self.wall += seconds
        self.mono += seconds


@pytest.fixture(params=["identity", "permissions"])
def rig(monkeypatch, request):
    clock = Clock()
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock.mono)
    source = Path("bot/broker_manager.py").read_text()
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "KrakenBroker")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_kraken_private_call")
    deadlines = []
    namespace = dict(
        Optional=Optional, Dict=Dict, Any=Any, time=clock,
        random=SimpleNamespace(uniform=lambda *args: 0),
        _KRAKEN_PRIVATE_CALL_SPACING_MIN_S=0, _KRAKEN_PRIVATE_CALL_SPACING_MAX_S=0,
        _KRAKEN_NONCE_MUTATING_METHODS={"AddOrder"},
        assert_mutation_deadline=deadlines.append, KrakenAPICategory=None,
        get_kraken_api_lock=threading.RLock, is_nonce_trading_paused=None,
        suppress_pykrakenapi_prints=nullcontext, logger=logging.getLogger(__name__),
    )
    exec(compile(ast.Module(body=[method], type_ignores=[]), "canonical-broker-method", "exec"), namespace)
    canonical = namespace["_kraken_private_call"]
    response = {"error": [], "result": {
        "apiKey": "synthetic-public-key", "iban": "SYNTHETIC-ACCOUNT", "validUntil": "0",  # pragma: allowlist secret (offline fixture)
        "queryFrom": "0", "queryTo": "0", "permissions": sorted(REQUIRED_READ_PERMISSIONS),
    }}
    calls = []

    def query(method, params):
        calls.append((method, params.copy()))
        clock.sleep(2)
        return response

    broker = SimpleNamespace(
        connected=True, broker_type="kraken", account_type="platform", user_id=None,
        api=SimpleNamespace(query_private=query), _hard_stopped=False,
        _gateway_url="", _gateway_only_mode=False, _api_call_lock=threading.RLock(),
        _kraken_rate_profile=None, _min_call_interval=134, _last_api_call_time=1000,
        nonce_manager=SimpleNamespace(can_issue_nonce=lambda key: True),
    )
    broker._kraken_private_call = lambda *args, **kw: canonical(broker, *args, **kw)
    provider = make_kraken_account_identity_provider(
        broker, account_scope="platform:kraken",
        approved_api_key_sha256=hashlib.sha256(b"synthetic-public-key").hexdigest(),
        approved_iban_sha256=hashlib.sha256(b"kraken\0SYNTHETIC-ACCOUNT").hexdigest(),
        reviewed_provider_id="reviewed-synthetic-provider", monitoring_category=object(), clock=clock.time,
    )
    denied = KrakenIdentityDenied
    if request.param == "permissions":
        provider = make_kraken_key_permission_provider(
            broker, account_scope="platform:kraken",
            approved_api_key_sha256=hashlib.sha256(b"synthetic-public-key").hexdigest(),
            reviewed_provider_id="reviewed-permission-provider", monitoring_category=object(), clock=clock.time,
        )
        denied = KeyInfoEvidenceDenied
    return SimpleNamespace(clock=clock, broker=broker, provider=provider, response=response, denied=denied,
                           calls=calls, deadlines=deadlines)


def test_canonical_rate_wait_excluded_but_transport_start_preserved(rig):
    observed = rig.provider()
    assert rig.clock.wall == 1136
    assert observed["observed_at_epoch"] == 1134
    assert observed["verified"] is True
    assert rig.calls == [("GetApiKeyInfo", {})]
    assert not rig.deadlines
    assert timing._LOCAL.capture is None


@pytest.mark.parametrize("failure", ["slow_http", "post_delay", "frozen_wall", "rollback",
                                    "substitution", "client_swap", "duplicate"])
def test_invalid_transport_never_refreshes_evidence(rig, failure):
    original = rig.broker._kraken_private_call
    query = rig.broker.api.query_private
    if failure == "slow_http":
        def slow(*args):
            rig.clock.sleep(61)
            return query(*args)
        rig.broker.api.query_private = slow

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        if failure == "post_delay":
            rig.clock.sleep(61)
        elif failure == "frozen_wall":
            rig.clock.mono += 61
        elif failure == "rollback":
            rig.clock.wall -= 10
        elif failure == "substitution":
            result = dict(result)
        elif failure == "client_swap":
            rig.broker.api = SimpleNamespace(query_private=query)
        elif failure == "duplicate":
            result = original(*args, **kwargs)
        return result
    rig.broker._kraken_private_call = wrapped
    with pytest.raises(rig.denied, match="clock_invalid_or_stale"):
        rig.provider()
    assert timing._LOCAL.capture is None


def test_uninstrumented_gateway_retains_conservative_deadline(rig):
    rig.broker._gateway_url = "synthetic-gateway"
    def gateway(*args):
        rig.clock.sleep(134)
        return rig.response
    rig.broker._call_via_gateway = gateway
    with pytest.raises(rig.denied, match="clock_invalid_or_stale"):
        rig.provider()


def test_mutation_uses_unchanged_nonce_and_deadline_guards(rig):
    with timing.capture_identity_read(rig.broker.api, rig.clock.time) as capture:
        rig.broker._kraken_private_call("AddOrder", {"synthetic": True})
    assert rig.calls == [("AddOrder", {"synthetic": True})]
    assert rig.deadlines == ["AddOrder", "AddOrder"]
    assert capture.attempts == 0
    rig.broker.nonce_manager.can_issue_nonce = lambda key: False
    with pytest.raises(RuntimeError, match="Nonce issuance blocked"):
        rig.broker._kraken_private_call("AddOrder", {})
    assert len(rig.calls) == 1


def test_thread_local_scope_and_exception_cleanup(rig):
    with timing.capture_identity_read(rig.broker.api, rig.clock.time) as outer:
        thread = threading.Thread(target=timing.query_identity_with_timing, args=(rig.broker.api, {}))
        thread.start()
        thread.join()
        assert outer.attempts == 0
        with pytest.raises(RuntimeError):
            with timing.capture_identity_read(rig.broker.api, rig.clock.time):
                raise RuntimeError("synthetic failure")
        assert timing._LOCAL.capture is outer
    assert timing._LOCAL.capture is None
