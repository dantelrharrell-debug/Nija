from types import SimpleNamespace

from bot import runtime_kraken_btnl_leveraged_v353_patch as v353


def _v352(scope=None):
    return SimpleNamespace(_margin_scope=lambda: dict(scope or {}))


def test_leveraged_buy_is_eligible_even_when_not_reduce_only():
    assert v353._leveraged_addorder(
        _v352(),
        "AddOrder",
        {"leverage": "2", "type": "buy", "reduce_only": False},
    ) is True


def test_scoped_leverage_is_eligible_even_when_payload_omits_leverage():
    assert v353._leveraged_addorder(
        _v352({"leverage": "3", "reduce_only": False}),
        "AddOrder",
        {"type": "buy"},
    ) is True


def test_spot_order_is_not_eligible():
    assert v353._leveraged_addorder(
        _v352(),
        "AddOrder",
        {"leverage": "1", "type": "buy", "reduce_only": False},
    ) is False


def test_non_order_private_call_is_not_eligible():
    assert v353._leveraged_addorder(
        _v352({"leverage": "2"}),
        "Balance",
        {"leverage": "2"},
    ) is False
