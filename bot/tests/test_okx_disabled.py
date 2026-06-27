import builtins


def test_okx_broker_connect_returns_before_sdk_import(monkeypatch):
    from bot.broker_manager import AccountType, OKXBroker

    real_import = builtins.__import__

    def guard_import(name, *args, **kwargs):
        if name == "okx" or name.startswith("okx."):
            raise AssertionError("OKX SDK must not be imported when OKX is disabled")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard_import)
    monkeypatch.delenv("NIJA_DISABLE_OKX", raising=False)

    broker = OKXBroker(account_type=AccountType.USER, user_id="read_only_container")

    assert broker.connect() is False
    assert broker.connected is False


def test_okx_adapter_connect_returns_before_sdk_import(monkeypatch):
    from bot.broker_integration import OKXBrokerAdapter

    real_import = builtins.__import__

    def guard_import(name, *args, **kwargs):
        if name == "okx" or name.startswith("okx."):
            raise AssertionError("OKX SDK must not be imported when OKX is disabled")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard_import)
    monkeypatch.delenv("NIJA_DISABLE_OKX", raising=False)

    assert OKXBrokerAdapter().connect() is False


def test_startup_validation_ignores_okx_credentials_when_disabled(monkeypatch):
    from bot.startup_validation import validate_exchange_configuration

    monkeypatch.setenv("OKX_API_KEY", "real-looking-okx-key-123456")
    monkeypatch.setenv("OKX_API_SECRET", "real-looking-okx-secret-123456")
    monkeypatch.setenv("OKX_PASSPHRASE", "passphrase")
    monkeypatch.delenv("KRAKEN_PLATFORM_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_PLATFORM_API_SECRET", raising=False)
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    monkeypatch.delenv("COINBASE_API_KEY", raising=False)
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    monkeypatch.delenv("COINBASE_PEM_CONTENT", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    result = validate_exchange_configuration()
    info = "\n".join(result.info)

    assert "OKX credentials present but ignored" in info
    assert "Viable brokers: 0" in info
