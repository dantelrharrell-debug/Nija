from pathlib import Path


def test_v91_is_installed_and_required_by_release_manifest():
    manifest = (Path(__file__).parents[1] / "runtime_release_manifest_patch.py").read_text()
    assert '("bot.global_drawdown_capital_authority_v91_patch", "install_import_hook")' in manifest
    assert '"global_drawdown_aggregate_guard": "NIJA_GLOBAL_DRAWDOWN_AGGREGATE_GUARD_READY"' in manifest
