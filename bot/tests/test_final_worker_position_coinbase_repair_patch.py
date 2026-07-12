import importlib
import os
import threading
import time


def _reload():
    module = importlib.import_module("final_worker_position_coinbase_repair_patch")
    return importlib.reload(module)


def test_position_dict_is_normalized_from_kraken_fields():
    module = _reload()
    position = {"vol": "2.5", "cost": "50.0"}
    result = module.normalize_position(position)
    assert result["quantity"] == 2.5
    assert result["size"] == 2.5
    assert result["entry_price"] == 20.0


def test_position_object_is_normalized():
    module = _reload()

    class Position:
        amount = "3"
        avg_price = "7.5"

    result = module.normalize_position(Position())
    assert result.quantity == 3.0
    assert result.entry_price == 7.5


def test_complete_single_line_pem_is_reframed():
    module = _reload()
    raw = "-----BEGIN PRIVATE KEY-----QUJDRA==-----END PRIVATE KEY-----"
    repaired = module._repair_pem(raw)
    assert repaired.startswith("-----BEGIN PRIVATE KEY-----\n")
    assert repaired.endswith("\n-----END PRIVATE KEY-----\n")
    assert "QUJDRA==" in repaired


def test_process_wide_duplicate_named_thread_is_suppressed():
    module = _reload()
    module.install()
    release = threading.Event()
    first = threading.Thread(target=lambda: release.wait(2), name="Trader-test_kraken", daemon=True)
    second_ran = threading.Event()
    second = threading.Thread(target=second_ran.set, name="Trader-test_kraken", daemon=True)
    first.start()
    time.sleep(0.02)
    second.start()
    time.sleep(0.02)
    assert first.is_alive()
    assert not second_ran.is_set()
    assert second.ident is None
    release.set()
    first.join(timeout=1)


def test_unrelated_thread_names_are_not_suppressed():
    module = _reload()
    module.install()
    done = threading.Event()
    thread = threading.Thread(target=done.set, name="ordinary-test-thread")
    thread.start()
    thread.join(timeout=1)
    assert done.is_set()
