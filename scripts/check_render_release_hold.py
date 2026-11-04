#!/usr/bin/env python3
"""Check repository deployment policy offline; never access or modify Render.

This check does not establish the live hold, release approval or trading authority.
The actual Render setting must be independently read back before release.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


class _UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently accepting the last value."""


def _mapping(loader: _UniqueLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            if key in result:
                raise ValueError("duplicate_blueprint_key")
            result[key] = loader.construct_object(value_node, deep=True)
        except TypeError as exc:
            raise ValueError("invalid_blueprint_key") from exc
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def verify_release_hold(source: str) -> None:
    """Require exactly one trading service with an explicit manual deploy hold."""
    try:
        document = yaml.load(source, Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError("invalid_blueprint_yaml") from exc
    if not isinstance(document, dict):
        raise ValueError("blueprint_mapping_required")

    services = []

    def visit(value: Any, ancestors: frozenset[int]) -> None:
        if not isinstance(value, (dict, list)):
            return
        identity = id(value)
        if identity in ancestors:
            raise ValueError("recursive_blueprint_alias")
        ancestors = ancestors | {identity}
        if isinstance(value, dict):
            if "services" in value:
                rows = value["services"]
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("invalid_blueprint_services")
                services.extend(row for row in rows if row.get("name") == "nija-trading-bot")
            for child in value.values():
                visit(child, ancestors)
        else:
            for child in value:
                visit(child, ancestors)

    visit(document, frozenset())
    if len(services) != 1:
        raise ValueError("exactly_one_trading_service_required")
    service = services[0]
    if service.get("type") != "web" or service.get("runtime") != "docker":
        raise ValueError("reviewed_trading_service_type_required")
    if "autoDeploy" in service:
        raise ValueError("legacy_auto_deploy_setting_refused")
    if service.get("autoDeployTrigger") != "off":
        raise ValueError("explicit_manual_release_hold_required")


def main() -> int:
    """Validate the supplied Blueprint without importing any trading modules."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("blueprint", nargs="?", type=Path, default=Path("render.yaml"))
    args = parser.parse_args()
    try:
        verify_release_hold(args.blueprint.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        parser.exit(1, "Render repository release hold check failed; inspect the Blueprint.\n")
    print("Repository release hold verified; live setting and release approval are not certified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
