"""Real publication/reader regressions using synthetic account owners only."""
import copy
import importlib.util
from pathlib import Path
import threading
from unittest.mock import Mock

import pytest

from bot.kraken_account_risk_publisher import ReviewedAccountRiskPublisher, RiskPublicationDenied
from bot.kraken_risk_evidence import make_kraken_risk_limits_provider

_spec = importlib.util.spec_from_file_location(
    "risk_publication_fixtures",
    Path(__file__).resolve().parents[1] / "bot/tests/test_kraken_risk_evidence.py",
)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)


@pytest.fixture
def publication():
    value = _fixtures.snapshot()
    owner = Mock(side_effect=lambda row: row == value)
    options = {
        "account_scope": _fixtures.ACCOUNT, "approved_api_key_sha256": _fixtures.PIN,
        "reviewed_provider_id": "synthetic-risk-provider",
        "reviewed_snapshot_source_id": value["source_id"],
        "reviewed_record_source_ids": _fixtures.BINDINGS,
        "clock": lambda: _fixtures.NOW,
    }
    publisher = ReviewedAccountRiskPublisher(
        **options, authenticate_current=owner, minimum_revision=0, independently_reviewed=True,
    )
    return publisher, value, owner, options


def test_missing_independent_review_denies_before_owner_reads(publication):
    _, _, owner, options = publication
    owner.reset_mock()
    with pytest.raises(RiskPublicationDenied):
        ReviewedAccountRiskPublisher(**options, authenticate_current=owner, minimum_revision=0)
    owner.assert_not_called()


def read(publisher):
    return publisher.read_snapshot(_fixtures.ACCOUNT, _fixtures.PIN)


def test_empty_publisher_never_invents_a_snapshot(publication):
    publisher, _, owner, _ = publication
    with pytest.raises(RiskPublicationDenied):
        read(publisher)
    owner.assert_not_called()


def test_actual_risk_reader_consumes_atomic_publication_without_authorizing_orders(publication):
    publisher, value, _, options = publication
    original = copy.deepcopy(value)
    publisher.publish(value)
    observation = make_kraken_risk_limits_provider(
        publisher, **options, independently_reviewed=True,
    )()
    assert value == original
    assert observation["observed_at_epoch"] == value["observed_at_epoch"]
    assert observation["snapshot_revision"] == value["revision"]
    assert observation["authorizes_orders"] is False


def test_publish_and_read_copies_do_not_alias_owner_or_caller_state(publication):
    publisher, value, owner, _ = publication
    publisher.publish(value)
    returned = read(publisher)
    returned["capital"]["real_capital"] = 0
    assert read(publisher)["capital"]["real_capital"] == 1000
    value["policy"]["halt_active"] = True
    with pytest.raises(RiskPublicationDenied):
        read(publisher)
    owner.side_effect = None
    owner.return_value = True
    with pytest.raises(RiskPublicationDenied):
        read(publisher)


@pytest.mark.parametrize("change", [
    lambda row: row.update(account="user:another:kraken"),
    lambda row: row.update(api_key_sha256="b" * 64),
    lambda row: row.pop("exposure"),
    lambda row: row["capital"].update(verified=False),
    lambda row: row["exposure"].update(total_gross_exposure_usd=0),
    lambda row: row["policy"].update(halt_active=True),
    lambda row: row["policy"].update(trading_allowed=False),
    lambda row: row["policy"].update(protective_exits_required=False),
    lambda row: row["exposure"]["positions"][0].update(protective_exit_verified=False),
    lambda row: row["capital"].update(observed_at_epoch=_fixtures.NOW-61),
    lambda row: row.update(observed_at_epoch=_fixtures.NOW+1),
    lambda row: row.update(revision=True),
    lambda row: row.update(revision=0),
    lambda row: row["capital"].update(real_capital=float("nan")),
    lambda row: row.update(notes="x" * 1024 * 1024),
])
def test_bad_replacement_withdraws_previous_healthy_publication(publication, change):
    publisher, value, _, _ = publication
    publisher.publish(value)
    value["revision"] += 1
    change(value)
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)
    with pytest.raises(RiskPublicationDenied):
        read(publisher)


def test_authenticated_halt_consumes_revision_and_prevents_healthy_replay(publication):
    publisher, value, _, _ = publication
    publisher.publish(value)
    healthy = copy.deepcopy(value)
    value["revision"] += 1
    value["policy"]["halt_active"] = True
    value["policy"]["revision"] += 1
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)
    value.clear()
    value.update(healthy)
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)
    value["revision"] += 2
    value["policy"]["revision"] += 2
    publisher.publish(value)
    assert read(publisher)["revision"] == healthy["revision"]+2


def test_authenticator_rechecked_before_and_after_every_read(publication):
    publisher, value, owner, _ = publication
    publisher.publish(value)
    owner.reset_mock(side_effect=True)
    owner.side_effect = [True, False]
    with pytest.raises(RiskPublicationDenied):
        read(publisher)
    assert owner.call_count == 2
    owner.side_effect = None
    owner.return_value = True
    with pytest.raises(RiskPublicationDenied):
        read(publisher)


@pytest.mark.parametrize("result", [False, None, 1, "yes"])
def test_truthy_flags_cannot_authenticate_publication(publication, result):
    publisher, value, owner, _ = publication
    owner.side_effect = None
    owner.return_value = result
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)


def test_authenticator_mutation_rejected(publication):
    publisher, value, owner, _ = publication
    def mutate(row):
        row["capital"]["real_capital"] = 0
        return True
    owner.side_effect = mutate
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)
    assert value["capital"]["real_capital"] == 1000


def test_reentrant_invalidation_cannot_resurrect_publication(publication):
    publisher, value, owner, _ = publication
    def invalidate(row):
        publisher.invalidate()
        return True
    owner.side_effect = invalidate
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)
    with pytest.raises(RiskPublicationDenied):
        read(publisher)


def test_invalidate_preserves_high_water(publication):
    publisher, value, _, _ = publication
    publisher.publish(value)
    publisher.invalidate()
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)
    value["revision"] += 1
    publisher.publish(value)
    assert read(publisher)["revision"] == value["revision"]


@pytest.mark.parametrize("kind", ["capital", "exposure", "policy"])
@pytest.mark.parametrize("change", ["rollback", "reuse"])
def test_record_revision_rollback_or_changed_value_reuse_denied(publication, kind, change):
    publisher, value, _, _ = publication
    publisher.publish(value)
    value["revision"] += 1
    if change == "rollback":
        value[kind]["revision"] -= 1
    else:
        value[kind]["observed_at_epoch"] += 1
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)
    with pytest.raises(RiskPublicationDenied):
        read(publisher)


def test_restart_starts_empty_and_respects_explicit_revision_floor(publication):
    _, value, owner, options = publication
    publisher = ReviewedAccountRiskPublisher(
        **options, authenticate_current=owner, minimum_revision=value["revision"], independently_reviewed=True,
    )
    with pytest.raises(RiskPublicationDenied):
        read(publisher)
    with pytest.raises(RiskPublicationDenied):
        publisher.publish(value)
    value["revision"] += 1
    publisher.publish(value)


def test_expiry_is_not_refreshed_by_reads_or_publication(publication):
    _, value, owner, options = publication
    now = [_fixtures.NOW]
    options["clock"] = lambda: now[0]
    publisher = ReviewedAccountRiskPublisher(
        **options, authenticate_current=owner, minimum_revision=0, independently_reviewed=True,
    )
    publisher.publish(value)
    now[0] += 51
    with pytest.raises(RiskPublicationDenied):
        read(publisher)
    now[0] -= 51
    with pytest.raises(RiskPublicationDenied):
        read(publisher)


def test_concurrent_read_cannot_observe_partial_replacement(publication):
    publisher, value, owner, _ = publication
    publisher.publish(value)
    entered, release, read_started, read_done = (threading.Event() for _ in range(4))
    errors, returned = [], []
    value["revision"] += 1
    def authenticate(row):
        if threading.current_thread().name == "risk-publisher":
            entered.set()
            assert release.wait(5)
        return row == value
    owner.side_effect = authenticate
    def publish():
        try:
            publisher.publish(value)
        except Exception as error:
            errors.append(error)
    def collect():
        read_started.set()
        try:
            returned.append(read(publisher))
        except Exception as error:
            errors.append(error)
        finally:
            read_done.set()
    writer = threading.Thread(target=publish, name="risk-publisher")
    reader = threading.Thread(target=collect)
    writer.start()
    assert entered.wait(5)
    reader.start()
    assert read_started.wait(5)
    assert not read_done.is_set()
    release.set()
    writer.join(5)
    reader.join(5)
    assert not writer.is_alive() and not reader.is_alive()
    assert errors == []
    assert returned == [value]


def test_callback_errors_are_redacted(publication):
    publisher, value, owner, _ = publication
    owner.side_effect = RuntimeError("synthetic-private-owner-detail")
    with pytest.raises(RiskPublicationDenied) as caught:
        publisher.publish(value)
    assert str(caught.value) == "risk_publication_rejected"
    assert caught.value.__suppress_context__ is True


def test_wrong_scope_read_withdraws_publication(publication):
    publisher, value, _, _ = publication
    publisher.publish(value)
    with pytest.raises(RiskPublicationDenied):
        publisher.read_snapshot("user:other:kraken", _fixtures.PIN)
    with pytest.raises(RiskPublicationDenied):
        read(publisher)
