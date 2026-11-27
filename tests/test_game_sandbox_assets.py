"""Immutable same-origin asset serving and startup regression tests."""
import hashlib
import json
from pathlib import Path

import pytest

from game_sandbox.app import create_app
from game_sandbox.ionos import PublishedGame
from game_sandbox.preview_assets import PreviewAssets, install_preview_ui
from test_game_sandbox import setup  # noqa: F401 - existing sandbox fixture


@pytest.fixture
def preview_bundle(tmp_path):
    root = tmp_path / 'public-preview'
    (root / 'assets').mkdir(parents=True)
    files = {'index.html': b'<main>EXISTING GAME FIXTURE</main>', 'assets/game.js': b'// existing export fixture'}
    for name, value in files.items():
        (root / name).write_bytes(value)
    manifest = {'version': 1, 'game_manifest': PublishedGame().digest,
                'files': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    pin = hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
    return root, manifest, pin


def repin(root: Path, manifest: dict) -> str:
    """Simulate an operator's independent approved-manifest pin, never auto-repin in production."""
    data = json.dumps(manifest).encode()
    (root / 'manifest.json').write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_verified_game_api_and_return_share_origin_without_directory_access(preview_bundle, setup):
    root, _, pin = preview_bundle
    app = create_app(setup[0])
    PreviewAssets(root, pin).register(app)
    client = app.test_client()
    assert client.get('/').headers['Location'] == '/trading-iq-challenge'
    response = client.get('/trading-iq-challenge')
    assert response.status_code == 200
    assert b'EXISTING GAME FIXTURE' in response.data
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/assets/game.js').mimetype == 'text/javascript'
    for path in ['/assets/manifest.json', '/assets/service.py', '/manifest.json', '/assets/../app.py']:
        assert client.get(path).status_code == 404
    assert client.get('/report').status_code == 200
    assert client.get('/sandbox/health').json['live_payments'] is False


@pytest.mark.parametrize('name', ['../service.py', 'assets/../index.html', '/index.html',
                                   'assets//game.js', 'assets/secret.env', 'assets/storage.sqlite3'])
def test_manifest_rejects_private_files_and_traversal(preview_bundle, name):
    root, manifest, _ = preview_bundle
    manifest['files'][name] = 'a' * 64
    with pytest.raises(ValueError, match='public_preview_asset_required'):
        PreviewAssets(root, repin(root, manifest))


def test_source_or_manifest_changes_fail_closed(preview_bundle):
    root, manifest, pin = preview_bundle
    with pytest.raises(ValueError, match='manifest_mismatch'):
        PreviewAssets(root, 'a' * 64)
    (root / 'assets/game.js').write_bytes(b'new unreviewed game')
    with pytest.raises(ValueError, match='asset_mismatch'):
        PreviewAssets(root, pin)


def test_symlinked_asset_is_never_served(preview_bundle, tmp_path):
    root, _, pin = preview_bundle
    original = root / 'assets/game.js'
    replacement = tmp_path / 'outside.js'
    replacement.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(replacement)
    with pytest.raises(ValueError, match='public_preview_asset_required'):
        PreviewAssets(root, pin)


def test_verified_bytes_are_immutable_after_startup(preview_bundle, setup):
    root, _, pin = preview_bundle
    assets = PreviewAssets(root, pin)
    (root / 'assets/game.js').write_bytes(b'unreviewed replacement')
    app = create_app(setup[0])
    assets.register(app)
    assert app.test_client().get('/assets/game.js').data == b'// existing export fixture'


def test_missing_or_wrong_game_contract_blocks_installation(preview_bundle, monkeypatch, setup):
    app = create_app(setup[0])
    monkeypatch.delenv('NIJA_IQ_SANDBOX_UI_ROOT', raising=False)
    with pytest.raises(ValueError, match='preview_root_required'):
        install_preview_ui(app)
    root, manifest, _ = preview_bundle
    manifest['game_manifest'] = 'a' * 64
    with pytest.raises(ValueError, match='preview_contract_required'):
        PreviewAssets(root, repin(root, manifest))


def test_enabled_staging_requires_ui_before_exposing_routes(monkeypatch):
    from flask import Flask
    from game_sandbox import app as api, staging_bootstrap, staging_entrypoint
    monkeypatch.setenv('NIJA_IQ_SANDBOX_ENABLED', 'true')
    monkeypatch.delenv('NIJA_IQ_SANDBOX_UI_ROOT', raising=False)
    monkeypatch.setattr(staging_bootstrap, 'validate_runtime', lambda: None)
    monkeypatch.setattr(api, 'from_environment', lambda: Flask('isolated_fixture'))
    with pytest.raises(ValueError, match='preview_root_required'):
        staging_entrypoint.create_staging_app()
