import importlib
import logging


def test_financial_disclaimers_emit_single_line_records(caplog):
    import bot.financial_disclaimers as fd

    fd = importlib.reload(fd)
    with caplog.at_level(logging.INFO, logger="nija.disclaimers"):
        fd.display_startup_disclaimers()
        fd.log_compliance_notice()

    messages = [record.getMessage() for record in caplog.records if record.name == "nija.disclaimers"]
    assert "A. Risk Disclosure" in messages
    assert "B. Platform Classification" in messages
    assert "C. Operational Model" in messages
    assert all("\n" not in message for message in messages)


def test_financial_disclaimers_are_process_idempotent(caplog):
    import bot.financial_disclaimers as fd

    fd = importlib.reload(fd)
    with caplog.at_level(logging.INFO, logger="nija.disclaimers"):
        fd.display_startup_disclaimers()
        fd.display_startup_disclaimers()

    messages = [record.getMessage() for record in caplog.records if record.name == "nija.disclaimers"]
    assert messages.count("A. Risk Disclosure") == 1
    assert any("already emitted" in message for message in messages)


def test_institutional_banner_emits_line_records_without_import_side_effect(caplog):
    import bot.institutional_disclaimers as inst

    with caplog.at_level(logging.INFO, logger="nija.bootstrap"):
        inst = importlib.reload(inst)

    assert not [record for record in caplog.records if record.name == "nija.bootstrap"]

    with caplog.at_level(logging.INFO, logger="nija.bootstrap"):
        inst.print_validation_banner()

    messages = [record.getMessage() for record in caplog.records if record.name == "nija.bootstrap"]
    assert any("MATHEMATICAL VALIDATION ONLY" in message for message in messages)
    assert all("\n" not in message for message in messages)
