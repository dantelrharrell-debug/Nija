from __future__ import annotations

from types import SimpleNamespace

from bot import capital_pipeline_margin_v158_patch as v158


def _v142(*, ttl: float = 90.0, fetch: float = 50.0):
    return SimpleNamespace(
        _freshness_ttl_seconds=lambda: ttl,
        _fetch_budget_seconds=lambda: fetch,
    )


def test_default_deadline_preserves_post_fetch_headroom(monkeypatch):
    monkeypatch.delenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", raising=False)
    monkeypatch.delenv(
        "NIJA_CAPITAL_RUNTIME_PIPELINE_POST_FETCH_HEADROOM_S",
        raising=False,
    )

    assert v158._bounded_deadline_seconds(_v142()) == 80.0


def test_legacy_70_second_env_cannot_shrink_required_headroom(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "70")
    monkeypatch.delenv(
        "NIJA_CAPITAL_RUNTIME_PIPELINE_POST_FETCH_HEADROOM_S",
        raising=False,
    )

    assert v158._bounded_deadline_seconds(_v142(ttl=90.0, fetch=50.0)) == 80.0


def test_deadline_never_broadens_immutable_freshness(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "500")

    assert v158._bounded_deadline_seconds(_v142(ttl=90.0, fetch=50.0)) == 80.0


def test_lower_legacy_deadline_is_also_treated_as_floor(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "40")

    assert v158._bounded_deadline_seconds(_v142()) == 80.0


def test_post_fetch_headroom_is_bounded(monkeypatch):
    monkeypatch.delenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", raising=False)
    monkeypatch.setenv(
        "NIJA_CAPITAL_RUNTIME_PIPELINE_POST_FETCH_HEADROOM_S",
        "999",
    )

    assert v158._bounded_deadline_seconds(_v142()) == 80.0


def test_small_ttl_still_fails_closed_inside_freshness(monkeypatch):
    monkeypatch.delenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", raising=False)
    monkeypatch.delenv(
        "NIJA_CAPITAL_RUNTIME_PIPELINE_POST_FETCH_HEADROOM_S",
        raising=False,
    )

    assert v158._bounded_deadline_seconds(_v142(ttl=45.0, fetch=30.0)) == 35.0


def test_patch_one_v142_owns_effective_deadline_after_outer_wrapper(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_RUNTIME_PIPELINE_DEADLINE_S", "70")

    fake = SimpleNamespace(
        _freshness_ttl_seconds=lambda: 90.0,
        _fetch_budget_seconds=lambda: 50.0,
        _runtime_pipeline_deadline_seconds=lambda: 70.0,
    )

    assert v158._patch_one_v142(fake) is True
    assert fake._runtime_pipeline_deadline_seconds() == 80.0
