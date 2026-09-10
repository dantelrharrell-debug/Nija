from types import SimpleNamespace

import bot.runtime_kraken_stale_flight_authority_bridge_v391_patch as v391


def test_v391_installs_existing_v287_recovery(monkeypatch):
    calls = []
    real_import = v391.importlib.import_module

    fake_v287 = SimpleNamespace(install=lambda: calls.append("install") or True)

    def fake_import(name):
        if name == "bot.runtime_kraken_position_flight_recovery_v287_patch":
            return fake_v287
        return real_import(name)

    monkeypatch.setattr(v391.importlib, "import_module", fake_import)

    assert v391._install_position_flight_recovery() is True
    assert calls == ["install"]
