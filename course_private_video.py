"""Opt-in private file streaming for the existing Foundations buyer portal."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from pathlib import Path

from flask import Response, request
from werkzeug.wsgi import wrap_file

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_MANIFEST_LIMIT = 32 * 1024


def _open_regular(root, name):
    """Open via a directory descriptor, without following a final symlink."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, _FLAGS, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("video_source_not_regular")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _allowed_root(root):
    resolved = root.resolve(strict=True)
    app = Path(__file__).resolve().parent
    return resolved == root and not any(
        base == resolved or base in resolved.parents for base in (app, Path("/tmp"), Path("/var/tmp"))
    )


def configured_catalog():
    """Return a safe empty catalog unless an operator pins a valid manifest."""
    root = Path(os.getenv("NIJA_COURSE_VIDEO_ROOT", ""))
    digest = os.getenv("NIJA_COURSE_VIDEO_MANIFEST_SHA256", "")
    if not root.is_absolute() or not _SHA.fullmatch(digest):
        return None, {}
    try:
        # Keep real media off the application tree, public static paths and tmp.
        if not _allowed_root(root):
            return None, {}
        with _open_regular(root, "manifest.json") as file:
            raw = file.read(_MANIFEST_LIMIT + 1)
        if len(raw) > _MANIFEST_LIMIT or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), digest):
            return None, {}
        entries = json.loads(raw)
        if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
            return None, {}
        catalog = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"id", "title", "sha256", "size_bytes"}:
                return None, {}
            key, title, sha, size = (entry[n] for n in ("id", "title", "sha256", "size_bytes"))
            if (not isinstance(key, str) or not _ID.fullmatch(key) or key in catalog
                    or not isinstance(title, str) or not title.strip() or len(title) > 120
                    or not isinstance(sha, str) or not _SHA.fullmatch(sha)
                    or type(size) is not int or not 1 <= size <= 2 * 1024**3):
                return None, {}
            catalog[key] = entry
        return root, catalog
    except (OSError, ValueError, RuntimeError):
        return None, {}


def open_media(root, entry):
    media = _open_regular(root, entry["sha256"] + ".mp4")
    if os.fstat(media.fileno()).st_size != entry["size_bytes"]:
        media.close()
        raise ValueError("video_size_mismatch")
    return media


def verify_video_inventory(root, catalog):
    """Offline operator check; do not rehash multi-GB media on every seek."""
    if not catalog or root is None:
        raise ValueError("video_catalog_unavailable")
    for entry in catalog.values():
        with open_media(root, entry) as media:
            actual = hashlib.file_digest(media, "sha256").hexdigest()
        if not hmac.compare_digest(actual, entry["sha256"]):
            raise ValueError("video_digest_mismatch")
    return len(catalog)


def video_response(root, entry):
    media = open_media(root, entry)
    response = Response(wrap_file(request.environ, media), mimetype="video/mp4", direct_passthrough=True)
    response.content_length = entry["size_bytes"]
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Disposition"] = "inline"
    try:
        return response.make_conditional(request.environ, accept_ranges=True,
                                         complete_length=entry["size_bytes"])
    except BaseException:
        media.close()
        raise
