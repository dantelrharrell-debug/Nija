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


def _mount_is_readonly(fd):
    """Check the actual mount of an opened descriptor, not path permissions."""
    return bool(os.fstatvfs(fd).f_flag & os.ST_RDONLY)


def _open_regular(root, name):
    """Open from a read-only mount without following a final symlink."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if not _mount_is_readonly(directory):
            raise ValueError("video_root_mount_not_readonly")
        fd = os.open(name, _FLAGS, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("video_source_not_regular")
        # A child bind mount can differ from the parent's mount flags.
        if not _mount_is_readonly(fd):
            raise ValueError("video_source_mount_not_readonly")
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
    from course_video_object import object_catalog_source

    source = object_catalog_source()
    if not _SHA.fullmatch(digest) or (source is None and not root.is_absolute()):
        return None, {}
    try:
        # Keep real media off the application tree, public static paths and tmp.
        if source is None:
            if not _allowed_root(root):
                return None, {}
            with _open_regular(root, "manifest.json") as file:
                raw = file.read(_MANIFEST_LIMIT + 1)
        else:
            raw = os.getenv("NIJA_COURSE_OBJECT_MANIFEST", "").encode()
        if len(raw) > _MANIFEST_LIMIT or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), digest):
            return None, {}
        entries = json.loads(raw)
        if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
            return None, {}
        catalog = {}
        fields = {"id", "title", "sha256", "size_bytes"}
        if source is not None:
            fields.add("version")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != fields:
                return None, {}
            key, title, sha, size = (entry[n] for n in ("id", "title", "sha256", "size_bytes"))
            if (not isinstance(key, str) or not _ID.fullmatch(key) or key in catalog
                    or not isinstance(title, str) or not title.strip() or len(title) > 120
                    or not isinstance(sha, str) or not _SHA.fullmatch(sha)
                    or type(size) is not int or not 1 <= size <= 2 * 1024**3):
                return None, {}
            if source is not None and not source.valid_version(entry["version"]):
                return None, {}
            catalog[key] = entry
        return source if source is not None else root, catalog
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
    from course_video_object import ObjectSource

    if isinstance(root, ObjectSource):
        for entry in catalog.values():
            root.verify(entry)
        return len(catalog)
    for entry in catalog.values():
        with open_media(root, entry) as media:
            actual = hashlib.file_digest(media, "sha256").hexdigest()
        if not hmac.compare_digest(actual, entry["sha256"]):
            raise ValueError("video_digest_mismatch")
    return len(catalog)


def video_response(root, entry):
    from course_video_object import ObjectSource

    if isinstance(root, ObjectSource):
        return root.response(entry)
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
