from __future__ import annotations

from types import SimpleNamespace

from bot import capital_pipeline_margin_v158_patch as v158


def _v142(*, ttl: float = 90.0, fetch: float = 50.0):
    return SimpleNamespace(
        _freshness_ttl_seconds=lambda: ttl,
        _fetch_budget_seconds=lambda: fetch,
    )


def test_default_deadline_leaves_publish_margin_inside_freshness(monkeypatch):
    monkeypatch.delenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_PIPELINE_PUBLISH_MARGIN_S", raising=False)

    assert v158._bounded_deadline_seconds(_v142()) == 70.0


def test_deadline_never_broadens_immutable_freshness(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "500")

    assert v158._bounded_deadline_seconds(_v142(ttl=90.0, fetch=50.0)) == 80.0


def test_stricter_operator_deadline_is_preserved(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "40")

    assert v158._bounded_deadline_seconds(_v142()) == 40.0


def test_publish_margin_is_bounded(monkeypatch):
    monkeypatch.delenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", raising=False)
    monkeypatch.setenv("NIJA_CAPITAL_PIPELINE_PUBLISH_MARGIN_S", "999")

    # margin clamps at 30s and total remains capped at TTL - 10s.
    assert v158._bounded_deadline_seconds(_v142()) == 80.0


def test_small_ttl_still_fails_closed_inside_freshness(monkeypatch):
    monkeypatch.delenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", raising=False)
    monkeypatch.delenv("NIJA_CAPITAL_PIPELINE_PUBLISH_MARGIN_S", raising=False)

    assert v158._bounded_deadline_seconds(_v142(ttl=45.0, fetch=30.0)) == 35.0
