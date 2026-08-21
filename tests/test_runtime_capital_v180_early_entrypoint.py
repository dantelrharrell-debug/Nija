from pathlib import Path


def test_v180_guard_is_armed_before_fast_guard_bundle_and_bot_main() -> None:
    source = (Path(__file__).parents[1] / "bot" / "bot.py").read_text(encoding="utf-8")
    canonical = source.split("if _canonical_fast_path_enabled():", 1)[1].split("else:", 1)[0]

    early_call = '_install_capital_v180_early(mode="canonical_fast")'
    bundle_call = "_install_guards(_FAST_PATH_INSTALLERS"

    assert "bot.runtime_capital_direct_refresh_downgrade_v180_patch" in source
    assert "_patch_capital_authority" in source
    assert "release_manifest_deferred=true" in source
    assert early_call in canonical
    assert bundle_call in canonical
    assert canonical.index(early_call) < canonical.index(bundle_call)
    assert source.index(early_call) < source.index("from bot.bot_main import main")


def test_v180_early_guard_is_fail_closed() -> None:
    source = (Path(__file__).parents[1] / "bot" / "bot.py").read_text(encoding="utf-8")

    assert "CAPITAL_V180_EARLY_ENTRYPOINT_FAILED" in source
    assert 'os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"' in source
    assert 'os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"' in source
    assert "v180 early capital guard failed; trading remains fail closed" in source
