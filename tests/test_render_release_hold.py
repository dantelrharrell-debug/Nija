"""Offline deployment-policy regressions; never contact production."""
from pathlib import Path

import pytest

from scripts.check_render_release_hold import verify_release_hold


SERVICE = '''services:
  - name: nija-trading-bot
    type: web
    runtime: docker
    autoDeployTrigger: "off"
'''


def test_repository_and_reviewed_manual_hold():
    verify_release_hold(SERVICE)
    verify_release_hold((Path(__file__).resolve().parents[1] / "render.yaml").read_text())


@pytest.mark.parametrize("trigger", ['commit', 'checksPass', 'false', 'off', 'null', '"OFF"'])
def test_automatic_and_ambiguous_triggers_are_refused(trigger):
    with pytest.raises(ValueError, match="explicit_manual"):
        verify_release_hold(SERVICE.replace('"off"', trigger))


def test_missing_explicit_hold_is_refused():
    with pytest.raises(ValueError, match="explicit_manual"):
        verify_release_hold(SERVICE.replace('    autoDeployTrigger: "off"\n', ''))


@pytest.mark.parametrize("legacy", ['true', 'false'])
def test_legacy_setting_is_refused_even_with_new_setting(legacy):
    with pytest.raises(ValueError, match="legacy_auto"):
        verify_release_hold(SERVICE + f"    autoDeploy: {legacy}\n")


def test_duplicate_key_cannot_hide_automatic_deploy():
    with pytest.raises(ValueError, match="duplicate_blueprint_key"):
        verify_release_hold(SERVICE + "    autoDeployTrigger: commit\n")


def test_nested_duplicate_service_is_refused():
    duplicate = '\nprojects:\n  - name: trading\n    environments:\n      - name: production\n'
    duplicate += '\n'.join('        ' + line for line in SERVICE.splitlines())
    with pytest.raises(ValueError, match="exactly_one"):
        verify_release_hold(SERVICE + duplicate)


@pytest.mark.parametrize("source", ['services: []', '[]', 'services: invalid', 'services: ['])
def test_missing_or_malformed_configuration_is_refused(source):
    with pytest.raises(ValueError):
        verify_release_hold(source)


def test_unrelated_service_does_not_satisfy_hold():
    with pytest.raises(ValueError, match="exactly_one"):
        verify_release_hold(SERVICE.replace('nija-trading-bot', 'dashboard'))


def test_recursive_yaml_alias_is_refused():
    with pytest.raises(ValueError):
        verify_release_hold(SERVICE + '\ncycle: &cycle\n  child: *cycle\n')


@pytest.mark.parametrize("prefix", [
    'ungrouped:\n',
    'projects:\n  - name: trading\n    environments:\n      - name: production\n',
])
def test_supported_nested_service_locations(prefix):
    indent = '  ' if prefix.startswith('ungrouped') else '        '
    verify_release_hold(prefix + '\n'.join(indent + line for line in SERVICE.splitlines()))


@pytest.mark.parametrize("real_service", ['services: []\n', SERVICE])
def test_unrelated_nested_services_cannot_satisfy_or_augment_hold(real_service):
    misplaced = 'metadata:\n' + '\n'.join('  ' + line for line in SERVICE.splitlines())
    with pytest.raises(ValueError, match="unsupported_blueprint_services_location"):
        verify_release_hold(real_service + misplaced)


@pytest.mark.parametrize("invalid", [
    'ungrouped: []', 'ungrouped: null', 'projects: {}', 'projects: [null]',
    'projects: [{environments: {}}]', 'projects: [{environments: [null]}]',
    'ungrouped: {services: {}}', 'projects: [{environments: [{services: null}]}]',
])
def test_malformed_supported_containers_fail_closed(invalid):
    with pytest.raises(ValueError):
        verify_release_hold(SERVICE + invalid)
