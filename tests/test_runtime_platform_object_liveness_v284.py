from __future__ import annotations

import threading
from enum import Enum
from types import SimpleNamespace

from bot import runtime_platform_object_liveness_v284_patch as v284
from bot import runtime_post_import_convergence_patch as post_import


class _BrokerType(Enum):
    COINBASE = "coinbase"
    OKX = "okx"


class _Broker:
    def __init__(self):
        self.account_type = "platform"
        self.credentials_configured = False
        self.connected = False


class _Manager:
    def __init__(self, *, finalized: bool = True):
        self._platform_brokers = {}
        self._platform_connected = {}
        self._platform_state = {}
        self._broker_payload_fsm = {}
        self._registry_meta_lock = threading.RLock()
        self._platform_init_lock = threading.Lock()
        self._broker_registration_complete = threading.Event()
        if finalized:
            self._broker_registration_complete.set()
        self.recorded = []
        self.events = []

    def _record_broker_registration(self, broker_type, broker):
        self.recorded.append((broker_type, broker))

    def _get_or_create_platform_event(self, broker_type):
        self.events.append(broker_type)
        return threading.Event()


class _BrokerModule:
    BrokerType = _BrokerType
    CoinbaseBroker = _Broker
    OKXBroker = _Broker
    _PLATFORM_BROKER_INSTANCES = {}
    GLOBAL_PLATFORM_BROKERS = {}
    _PLATFORM_BROKER_CONNECTED = {}
    _PLATFORM_BROKER_REGISTRY_LOCK = threading.RLock()


def _reset_module_registries():
    _BrokerModule._PLATFORM_BROKER_INSTANCES = {}
    _BrokerModule.GLOBAL_PLATFORM_BROKERS = {}
    _BrokerModule._PLATFORM_BROKER_CONNECTED = {}


def test_v284_requires_exact_credential_presence(monkeypatch):
    monkeypatch.delenv("COINBASE_API_KEY", raising=False)
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
    monkeypatch.delenv("COINBASE_PEM_CONTENT", raising=False)
    assert v284._credential_proof("coinbase") is False

    monkeypatch.setenv("COINBASE_API_KEY", "key")
    monkeypatch.setenv("COINBASE_PEM_CONTENT", "pem")
    assert v284._credential_proof("coinbase") is True

    monkeypatch.delenv("OKX_API_KEY", raising=False)
    monkeypatch.delenv("OKX_API_SECRET", raising=False)
    monkeypatch.delenv("OKX_API_PASSPHRASE", raising=False)
    monkeypatch.delenv("OKX_PASSPHRASE", raising=False)
    assert v284._credential_proof("okx") is False

    monkeypatch.setenv("OKX_API_KEY", "key")
    monkeypatch.setenv("OKX_API_SECRET", "secret")
    monkeypatch.setenv("OKX_PASSPHRASE", "pass")
    assert v284._credential_proof("okx") is True


def test_v284_constructs_disconnected_platform_object_only_after_env_proof(monkeypatch):
    monkeypatch.setattr(v284, "_credential_proof", lambda venue: True)
    broker = v284._construct_platform_broker(_BrokerModule, "coinbase")
    assert broker.account_type == "platform"
    assert broker.credentials_configured is True
    assert broker.connected is False


def test_v284_does_not_create_while_registration_is_in_progress(monkeypatch):
    manager = _Manager(finalized=False)
    _reset_module_registries()
    monkeypatch.setattr(v284, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v284, "_broker_module", lambda: _BrokerModule)
    monkeypatch.setattr(v284, "_configured_and_allowed", lambda venue: True)

    outcomes = v284.reconcile_once()
    assert outcomes == {
        "coinbase": "registration_in_progress",
        "okx": "registration_in_progress",
    }
    assert manager._platform_brokers == {}
    assert _BrokerModule._PLATFORM_BROKER_INSTANCES == {}


def test_v284_publishes_missing_object_as_disconnected(monkeypatch):
    manager = _Manager(finalized=True)
    _reset_module_registries()
    broker = _Broker()
    broker.credentials_configured = True

    real_import = v284.importlib.import_module

    fake_mabm = SimpleNamespace(
        ConnectionState=SimpleNamespace(NOT_STARTED="not_started"),
        broker_registry={"coinbase": {}, "okx": {}},
    )
    fake_capital_fsm = SimpleNamespace(BrokerPayloadFSM=lambda broker_id: SimpleNamespace(broker_id=broker_id))

    def fake_import(name):
        if name == "bot.multi_account_broker_manager":
            return fake_mabm
        if name == "bot.capital_flow_state_machine":
            return fake_capital_fsm
        return real_import(name)

    monkeypatch.setattr(v284.importlib, "import_module", fake_import)

    outcome = v284._publish_missing_object(manager, _BrokerModule, "coinbase", broker)
    assert outcome == "registered_missing_object"
    assert manager._platform_brokers[_BrokerType.COINBASE] is broker
    assert manager._platform_connected["coinbase"] is False
    assert manager._platform_state["coinbase"] == "not_started"
    assert _BrokerModule._PLATFORM_BROKER_INSTANCES["coinbase"] is broker
    assert _BrokerModule.GLOBAL_PLATFORM_BROKERS["coinbase"] is True
    assert _BrokerModule._PLATFORM_BROKER_CONNECTED["coinbase"] is False
    assert manager.recorded == [(_BrokerType.COINBASE, broker)]
    assert manager.events == [_BrokerType.COINBASE]


def test_v284_existing_global_object_is_delegated_not_recreated(monkeypatch):
    manager = _Manager(finalized=True)
    _reset_module_registries()
    existing = _Broker()
    _BrokerModule._PLATFORM_BROKER_INSTANCES["coinbase"] = existing

    monkeypatch.setattr(v284, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v284, "_broker_module", lambda: _BrokerModule)
    monkeypatch.setattr(v284, "_configured_and_allowed", lambda venue: venue == "coinbase")

    outcomes = v284.reconcile_once()
    assert outcomes["coinbase"] == "global_present_wait_v280"
    assert manager._platform_brokers == {}
    assert _BrokerModule._PLATFORM_BROKER_INSTANCES["coinbase"] is existing


def test_v284_install_delegates_real_connect_to_v280(monkeypatch):
    monkeypatch.setattr(v284, "_register_manifest", lambda: True)
    monkeypatch.setattr(
        v284,
        "reconcile_once",
        lambda: {
            "coinbase": "registered_missing_object",
            "okx": "not_configured_or_policy_disabled",
        },
    )
    calls = []
    monkeypatch.setattr(v284, "_delegate_v280", lambda: calls.append("v280") or {"coinbase": "connected"})

    assert v284.install() is True
    assert calls == ["v280"]


def test_post_import_orders_v284_before_v280_and_v283(monkeypatch):
    order = []
    monkeypatch.setattr(post_import, "_canonicalize_alias", lambda: False)
    monkeypatch.setattr(post_import, "_apply_broker_threshold", lambda: 1)
    monkeypatch.setattr(post_import, "_patch_quiescence_audit", lambda: True)

    for name in (
        "_install_v154_recovery", "_install_v155_nonce_maturity", "_install_v157_runtime_quality",
        "_install_v158_capital_margin", "_install_v161_capital_position_convergence",
        "_install_v162_late_observation_fence", "_install_v163_activation_convergence",
        "_install_v164_capital_publication_liveness", "_install_v165_capital_publication_scheduling",
        "_install_v167_refresh_demand", "_install_v209_zero_balance_completeness",
        "_install_v224_exchange_reject_provenance", "_install_v228_exchange_reject_dispatch_provenance",
        "_install_v229_capital_provenance_alias", "_install_v232_heartbeat_execution_quality",
        "_install_v233_heartbeat_terminal_authority", "_install_v234_kraken_read_lock_recovery",
        "_install_v236_heartbeat_final_submit", "_install_v237_kraken_local_contention_health",
        "_install_v238_heartbeat_marker_convergence", "_install_v239_all_account_profit_targets",
        "_install_v240_heartbeat_terminal_lifecycle", "_install_v241_kraken_local_contention_alias",
        "_install_v242_kraken_local_contention_instance", "_install_v244_heartbeat_broker_manager_terminal",
        "_install_v263_heartbeat_state_machine_gate",
    ):
        monkeypatch.setattr(post_import, name, lambda: True)

    monkeypatch.setattr(post_import, "_install_v267_capital_position_liveness", lambda: order.append("v267") or True)
    monkeypatch.setattr(post_import, "_install_v268_platform_kraken_registry_liveness", lambda: order.append("v268") or True)
    monkeypatch.setattr(post_import, "_install_v284_platform_object_liveness", lambda: order.append("v284") or True)
    monkeypatch.setattr(post_import, "_install_v280_platform_activation_liveness", lambda: order.append("v280") or True)
    monkeypatch.setattr(post_import, "_install_v283_all_account_coverage_liveness", lambda: order.append("v283") or True)

    assert post_import._iteration() is True
    assert order == ["v267", "v268", "v284", "v280", "v283"]
    assert post_import._LAST_PREREQUISITES["v284_platform_object_liveness"] is True
