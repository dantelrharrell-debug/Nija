"""Serve a reviewed copy of the existing game from the sandbox's own origin.

No downloads, source rewriting or directory browsing occurs at runtime. Deployment
must supply the already integrated existing UI and an independently pinned manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .ionos import PublishedGame

MAX_FILES = 256
MAX_BYTES = 32 * 1024 * 1024
SUFFIXES = {'.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
            '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg',
            '.webp': 'image/webp', '.svg': 'image/svg+xml', '.woff2': 'font/woff2'}
UI_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self' https://checkout.stripe.com"
)


class PreviewAssets:
    """Cache only verified public assets; any mismatch prevents startup."""

    def __init__(self, root: Path, manifest_sha256: str, game_manifest: str | None = None) -> None:
        if game_manifest is not None and not re.fullmatch(r'[a-f0-9]{64}', game_manifest):
            raise ValueError('reviewed_game_manifest_pin_required')
        if not root.is_absolute() or root.resolve() != root or not root.is_dir():
            raise ValueError('reviewed_preview_root_required')
        if not re.fullmatch(r'[a-f0-9]{64}', manifest_sha256 or ''):
            raise ValueError('reviewed_preview_manifest_pin_required')
        manifest_path = root / 'manifest.json'
        if manifest_path.is_symlink():
            raise ValueError('reviewed_preview_manifest_required')
        with manifest_path.open('rb') as source:
            raw = source.read(65537)
        if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != manifest_sha256:
            raise ValueError('reviewed_preview_manifest_mismatch')
        manifest = json.loads(raw)
        if (not isinstance(manifest, dict)
                or set(manifest) != {'version', 'game_manifest', 'files'}
                or type(manifest['version']) is not int or manifest['version'] != 1
                or manifest['game_manifest'] != (game_manifest if game_manifest is not None else PublishedGame().digest)
                or not isinstance(manifest['files'], dict)
                or not 2 <= len(manifest['files']) <= MAX_FILES
                or 'index.html' not in manifest['files']):
            raise ValueError('reviewed_preview_contract_required')
        self.files: dict[str, tuple[bytes, str]] = {}
        total = 0
        for name, expected in manifest['files'].items():
            if (not isinstance(name, str) or len(name) > 240
                    or not re.fullmatch(r'[A-Za-z0-9_./-]+', name)
                    or any(part in {'', '.', '..'} for part in name.split('/'))
                    or (name != 'index.html' and not name.startswith('assets/'))
                    or PurePosixPath(name).suffix not in SUFFIXES
                    or not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected)):
                raise ValueError('public_preview_asset_required')
            target = root / name
            if target.resolve() != target or not target.is_file():
                raise ValueError('public_preview_asset_required')
            with target.open('rb') as source:
                content = source.read(MAX_BYTES - total + 1)
            total += len(content)
            if total > MAX_BYTES or hashlib.sha256(content).hexdigest() != expected:
                raise ValueError('reviewed_preview_asset_mismatch')
            self.files[name] = (content, SUFFIXES[PurePosixPath(name).suffix])
        # Bytes are immutable after verification, closing a file-change/read race.
        self.manifest_sha256 = manifest_sha256

    def register(self, app: Any) -> None:
        """Install the existing game routes without any directory fallback."""
        from flask import Response, jsonify, redirect

        @app.get('/')
        def preview_root() -> Any:
            return redirect('/trading-iq-challenge', code=302)

        @app.get('/trading-iq-challenge')
        def preview_game() -> Any:
            content, mime = self.files['index.html']
            return Response(content, mimetype=mime)

        @app.get('/assets/<path:name>')
        def preview_asset(name: str) -> Any:
            asset = self.files.get('assets/' + name)
            if asset is None:
                return jsonify(error='not_found'), 404
            return Response(asset[0], mimetype=asset[1])



def install_preview_ui(app: Any) -> PreviewAssets:
    """Require the reviewed frontend deployment package before enabling staging."""
    root = os.environ.get('NIJA_IQ_SANDBOX_UI_ROOT', '')
    pin = os.environ.get('NIJA_IQ_SANDBOX_UI_MANIFEST_SHA256', '')
    if not root:
        raise ValueError('reviewed_preview_root_required')
    assets = PreviewAssets(Path(root), pin, app.config.get('NIJA_IQ_MANIFEST_SHA256'))
    assets.register(app)
    return assets
