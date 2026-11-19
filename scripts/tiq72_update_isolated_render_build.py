#!/usr/bin/env python3
"""Guarded existing-service Render build-command change; never deploys or enables payments.

For operator use with RENDER_API_KEY in protected environment only.
No API token, response body, secret, database URL, or customer record is printed.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

SERVICE = "srv-dbqeqgqfngtc73fcphhg"
WORKSPACE = "tea-d3qjmmc9c44c73cqvpug"
NAME = "nija-tiq72-upgrade6-isolated-test"
REPO = "https://github.com/dantelrharrell-debug/Nija"
OLD_BUILD = (
    "node --version && python3 -m venv /opt/render/project/src/.venv "
    "&& /opt/render/project/src/.venv/bin/python -m pip install "
    "-r web/trading-challenge/server/requirements-tiq72-preflight.txt"
)
NEW_BUILD = "bash scripts/tiq72-isolated-render-build.sh"
START = "node web/trading-challenge/server/tiq72-upgrade6-holding-http.mjs"
API_URL = f"https://api.render.com/v1/services/{SERVICE}"
APPROVAL = "APPROVE_EXISTING_ISOLATED_TEST_BUILD_ONLY"


class GuardDenied(Exception):
    pass


def build_command(service: object) -> str:
    if not isinstance(service, dict):
        raise GuardDenied("invalid_service")
    details = service.get("serviceDetails")
    if not isinstance(details, dict):
        raise GuardDenied("invalid_service_details")
    native = details.get("envSpecificDetails")
    if isinstance(native, dict) and isinstance(native.get("buildCommand"), str):
        return native["buildCommand"]
    if isinstance(details.get("buildCommand"), str):
        return details["buildCommand"]
    raise GuardDenied("missing_current_build_command")


def assert_identity(service: object) -> str:
    if not isinstance(service, dict) or any((
        service.get("id") != SERVICE,
        service.get("ownerId") != WORKSPACE,
        service.get("name") != NAME,
        service.get("repo") != REPO,
        service.get("branch") != "main",
        service.get("rootDir") != "",
        service.get("type") != "web_service",
        service.get("autoDeployTrigger") != "off",
    )):
        raise GuardDenied("isolated_service_identity_mismatch")
    details = service.get("serviceDetails")
    if not isinstance(details, dict):
        raise GuardDenied("isolated_service_type_mismatch")
    native = details.get("envSpecificDetails")
    start = native.get("startCommand") if isinstance(native, dict) else details.get("startCommand")
    if start != START:
        raise GuardDenied("holding_server_start_command_changed")
    command = build_command(service)
    if command not in (OLD_BUILD, NEW_BUILD):
        raise GuardDenied("unexpected_build_command_requires_manual_review")
    return command


def http_json(method: str, token: str, payload: dict | None = None) -> dict:
    if not isinstance(token, str) or len(token.strip()) < 16:
        raise GuardDenied("protected_render_api_key_required")
    if method not in ("GET", "PATCH"):
        raise GuardDenied("invalid_http_method")
    data = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    req = urllib.request.Request(
        API_URL, data=data,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/json", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            if response.status != 200:
                raise GuardDenied("render_api_unexpected_status")
            raw = response.read(131073)
        if len(raw) > 131072:
            raise GuardDenied("render_api_response_too_large")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise GuardDenied("render_api_response_shape_invalid")
        return body
    except (urllib.error.URLError, ValueError, OSError):
        # Never include raw provider diagnostics: they can contain auth context.
        raise GuardDenied("render_api_unavailable_or_denied") from None


def reconcile_build(*, apply: bool, approval: str = "",
                    request=http_json, token: str = "") -> str:
    current = assert_identity(request("GET", token))
    if current == NEW_BUILD:
        return "existing_isolated_build_setting_already_updated"
    if not apply:
        return "reviewed_isolated_test_build_change_ready_not_applied"
    if approval != APPROVAL:
        raise GuardDenied("operator_review_required")
    # Minimal-diff PATCH: no branch, start command, service plan, env vars,
    # secrets, database, webhook, or trading configuration.
    request("PATCH", token, {"serviceDetails": {"buildCommand": NEW_BUILD}})
    observed = assert_identity(request("GET", token))
    if observed != NEW_BUILD:
        raise GuardDenied("render_build_readback_mismatch")
    return "isolated_test_build_setting_updated_deploy_still_required"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    try:
        result = reconcile_build(
            apply=args.apply,
            approval=os.getenv("TIQ72_RENDER_BUILD_CHANGE_APPROVAL", ""),
            token=os.getenv("RENDER_API_KEY", ""),
        )
        print("TIQ72_RENDER_BUILD: " + result)
        return 0
    except GuardDenied as exc:
        print("TIQ72_RENDER_BUILD: blocked " + str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
