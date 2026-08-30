from __future__ import annotations

from types import SimpleNamespace

import bot.runtime_heartbeat_position_cap_result_bridge_v303_patch as v303


def test_cap_rejection_detail_requires_failed_status_and_explicit_cap_reason():
    assert v303._cap_rejection_detail({"status": "rejected", "error": "POSITION_CAP_EXCEEDED: Position cap reached: 2/1"})
    assert v303._cap_rejection_detail({"status": "error", "error": "Position cap reached: 2/1"})
    assert v303._cap_rejection_detail({"status": "filled", "error": "POSITION_CAP_EXCEEDED"}) == ""
    assert v303._cap_rejection_detail({"status": "rejected", "error": "minimum notional"}) == ""
    assert v303._cap_rejection_detail(None) == ""


def _fake_v273(*, trusted: bool = True):
    calls: list[tuple[str, str, str]] = []

    def _trusted_heartbeat_probe():
        return trusted, "HEARTBEAT_TRADE" if trusted else "not_heartbeat_thread"

    def _set_cap_block(detail: str, *, symbol: str = "", side: str = ""):
        calls.append((detail, symbol, side))

    return SimpleNamespace(
        _trusted_heartbeat_probe=_trusted_heartbeat_probe,
        _set_cap_block=_set_cap_block,
        calls=calls,
    )


def test_wrapper_bridges_exact_heartbeat_buy_cap_rejection_without_mutating_result(monkeypatch):
    fake = _fake_v273(trusted=True)
    monkeypatch.setattr(v303, "_v273", lambda: fake)
    result = {"status": "rejected", "error": "POSITION_CAP_EXCEEDED: Position cap reached: 2/1", "order_id": None}

    def submit(*args, **kwargs):
        return result

    wrapped = v303._wrap_submit(submit)
    observed = wrapped(symbol="BTC-USD", side="buy", quantity=12.5, strategy="HEARTBEAT_TRADE")

    assert observed is result
    assert fake.calls == [(result["error"], "BTC-USD", "BUY")]


def test_wrapper_does_not_bridge_ordinary_strategy(monkeypatch):
    fake = _fake_v273(trusted=True)
    monkeypatch.setattr(v303, "_v273", lambda: fake)
    result = {"status": "rejected", "error": "POSITION_CAP_EXCEEDED"}
    wrapped = v303._wrap_submit(lambda *args, **kwargs: result)

    assert wrapped(symbol="BTC-USD", side="buy", strategy="APEX") is result
    assert fake.calls == []


def test_wrapper_does_not_bridge_sell(monkeypatch):
    fake = _fake_v273(trusted=True)
    monkeypatch.setattr(v303, "_v273", lambda: fake)
    result = {"status": "rejected", "error": "POSITION_CAP_EXCEEDED"}
    wrapped = v303._wrap_submit(lambda *args, **kwargs: result)

    assert wrapped(symbol="BTC-USD", side="sell", strategy="HEARTBEAT_TRADE") is result
    assert fake.calls == []


def test_wrapper_does_not_bridge_non_cap_rejection(monkeypatch):
    fake = _fake_v273(trusted=True)
    monkeypatch.setattr(v303, "_v273", lambda: fake)
    result = {"status": "rejected", "error": "MIN_NOTIONAL"}
    wrapped = v303._wrap_submit(lambda *args, **kwargs: result)

    assert wrapped(symbol="BTC-USD", side="buy", strategy="HEARTBEAT_TRADE") is result
    assert fake.calls == []


def test_wrapper_fails_closed_when_startup_probe_not_trusted(monkeypatch):
    fake = _fake_v273(trusted=False)
    monkeypatch.setattr(v303, "_v273", lambda: fake)
    result = {"status": "rejected", "error": "POSITION_CAP_EXCEEDED"}
    wrapped = v303._wrap_submit(lambda *args, **kwargs: result)

    assert wrapped(symbol="BTC-USD", side="buy", strategy="HEARTBEAT_TRADE") is result
    assert fake.calls == []
