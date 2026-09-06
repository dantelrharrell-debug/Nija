from bot import runtime_registered_user_protection_proof_v379_patch as v379


def _position(**overrides):
    row = {
        "account": "user:alice:kraken",
        "symbol": "BTC-USD",
        "quantity": 0.01,
        "entry_price": 100.0,
        "authoritative_snapshot_adopted": True,
        "cost_basis_verified": True,
        "auto_exit_blocked": False,
        "universal_four_way_policy_complete": True,
        "protective_stop_verified": True,
        "protective_take_profit_verified": True,
        "protective_trailing_stop_verified": True,
        "protective_trailing_take_profit_verified": True,
        "protective_exit_verified": True,
    }
    row.update(overrides)
    return row


def test_live_user_position_requires_all_four_legs(monkeypatch):
    monkeypatch.setattr(
        v379,
        "_coverage",
        lambda: {
            "expected_accounts": ("platform:kraken", "user:alice:kraken"),
            "pending": {},
            "positions": (_position(),),
        },
    )
    result = v379.evaluate_once()
    proof = result["accounts"]["user:alice:kraken"]
    assert result["ready"] is True
    assert proof["live_position_proof"] is True
    assert proof["positions"][0]["sl"] is True
    assert proof["positions"][0]["tp"] is True
    assert proof["positions"][0]["tsl"] is True
    assert proof["positions"][0]["ttp"] is True
    assert proof["natural_exit_fill_proof"] is False
    assert proof["forced_test_trade"] is False


def test_missing_trailing_take_profit_keeps_user_proof_pending(monkeypatch):
    monkeypatch.setattr(
        v379,
        "_coverage",
        lambda: {
            "expected_accounts": ("user:alice:kraken",),
            "pending": {"user:alice:kraken": ("universal_four_way_policy_incomplete:BTC-USD",)},
            "positions": (_position(protective_trailing_take_profit_verified=False, protective_exit_verified=False),),
        },
    )
    result = v379.evaluate_once()
    assert result["ready"] is False
    assert result["accounts"]["user:alice:kraken"]["live_position_proof"] is False


def test_safe_idle_user_is_not_misrepresented_as_live_position_proof(monkeypatch):
    monkeypatch.setattr(
        v379,
        "_coverage",
        lambda: {
            "expected_accounts": ("user:alice:kraken",),
            "pending": {},
            "positions": (),
        },
    )
    result = v379.evaluate_once()
    proof = result["accounts"]["user:alice:kraken"]
    assert result["ready"] is True
    assert proof["safe_idle_no_open_positions"] is True
    assert proof["live_position_proof"] is False


def test_snapshot_blocker_prevents_safe_idle_claim(monkeypatch):
    monkeypatch.setattr(
        v379,
        "_coverage",
        lambda: {
            "expected_accounts": ("user:alice:kraken",),
            "pending": {"user:alice:kraken": ("authoritative_position_fetch_unproven",)},
            "positions": (),
        },
    )
    result = v379.evaluate_once()
    assert result["ready"] is False
    assert result["accounts"]["user:alice:kraken"]["safe_idle_no_open_positions"] is False
