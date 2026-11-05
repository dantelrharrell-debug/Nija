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
    allowed_service_paths: set[tuple[Any, ...]] = set()

    def collect(container: dict[Any, Any], path: tuple[Any, ...]) -> None:
        if "services" not in container:
            return
        rows = container["services"]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid_blueprint_services")
        allowed_service_paths.add((*path, "services"))
        services.extend(row for row in rows if row.get("name") == "nija-trading-bot")

    collect(document, ())
    if "ungrouped" in document:
        ungrouped = document["ungrouped"]
        if not isinstance(ungrouped, dict):
            raise ValueError("invalid_blueprint_ungrouped")
        collect(ungrouped, ("ungrouped",))
    if "projects" in document:
        projects = document["projects"]
        if not isinstance(projects, list) or any(not isinstance(row, dict) for row in projects):
            raise ValueError("invalid_blueprint_projects")
        for project_index, project in enumerate(projects):
            if "environments" not in project:
                continue
            environments = project["environments"]
            if not isinstance(environments, list) or any(not isinstance(row, dict) for row in environments):
                raise ValueError("invalid_blueprint_environments")
            for environment_index, environment in enumerate(environments):
                collect(environment, ("projects", project_index, "environments", environment_index))

    def visit(value: Any, path: tuple[Any, ...], ancestors: frozenset[int]) -> None:
        if not isinstance(value, (dict, list)):
            return
        identity = id(value)
        if identity in ancestors:
            raise ValueError("recursive_blueprint_alias")
        ancestors = ancestors | {identity}
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = (*path, key)
                if key == "services" and child_path not in allowed_service_paths:
                    raise ValueError("unsupported_blueprint_services_location")
                visit(child, child_path, ancestors)
        else:
            for index, child in enumerate(value):
                visit(child, (*path, index), ancestors)

    visit(document, (), frozenset())
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
