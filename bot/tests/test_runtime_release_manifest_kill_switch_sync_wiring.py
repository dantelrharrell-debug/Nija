from __future__ import annotations

import bot.runtime_release_manifest_patch as manifest


def test_kill_switch_coordinator_sync_is_required_by_release_manifest():
    assert (
        "bot.kill_switch_coordinator_sync_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert (
        manifest._REQUIRED_FLAGS["kill_switch_coordinator_sync"]
        == "NIJA_KILL_SWITCH_COORDINATOR_SYNC_INSTALLED"
    )
