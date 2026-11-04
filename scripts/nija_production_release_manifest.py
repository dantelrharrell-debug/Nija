#!/usr/bin/env python3
"""Offline, post-commit release inventory. Never installs, approves or deploys anything.

Only content digests and digest-pinned external references are serialized. The
manifest is unsigned: authenticate its SHA-256 through a separate reviewed channel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import Any


FORMAT = "nija-production-release-manifest-v1"
BINDINGS = frozenset({"account", "broker", "redis", "ledger", "signing", "commissioning"})
HEX = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
IMAGE = re.compile(r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}\Z")
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 32 * 1024 * 1024
ROOT_RELEASE_FILES = frozenset({
    ".dockerignore", "railway.json", "render.yaml", "runtime.txt",
    "main.py", "bot.py", "start.sh",
})


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={key: value for key, value in os.environ.items()
             if not key.startswith("GIT_")},
    )
    if result.returncode:
        raise ValueError("git_read_failed")
    return result.stdout


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular_bytes(path: Path, limit: int) -> bytes:
    # Refuse symlink traversal, including parent directories.
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("symlink_refused")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("regular_bounded_file_required")
        raw = source.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("file_too_large")
    return raw


def _commit(root: Path, value: str) -> None:
    if not isinstance(value, str) or not COMMIT.fullmatch(value):
        raise ValueError("exact_full_commit_required")
    if _git(root, "rev-parse", "--verify", value + "^{commit}").decode().strip() != value:
        raise ValueError("exact_commit_object_required")


def _source_path(value: str) -> bool:
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError("invalid_source_path")
    if "tests" in path.parts or path.name.startswith("test_"):
        return False
    if len(path.parts) == 1:
        return path.suffix == ".py"
    return (
        path.parts[0] in {"bot", "scripts"} and path.suffix == ".py"
        or path.parts[0] == "scripts" and path.suffix == ".sh"
        or path.parts[0] == "k8s" and path.suffix in {".yaml", ".yml", ".json"}
    )


def _protected(value: str) -> bool:
    path = PurePosixPath(value)
    source = _source_path(value)
    return (
        len(path.parts) == 1 and path.name.startswith("requirements") and path.suffix == ".txt"
        or len(path.parts) == 1 and (
            path.name in ROOT_RELEASE_FILES or path.name.startswith(("Dockerfile", "docker-compose"))
        )
        or path.parts[:2] == (".github", "workflows")
        or path.parts[0] == "k8s" and source
        or path.parts[0] == "bot" and source and (
            any(term in path.name for term in ("provider", "evidence", "commissioning", "collector"))
            or path.name in {
                "account_order_admission.py", "order_admission_policy.py",
                "startup_verification_plan.py", "kraken_operator_authorization.py",
            }
        )
    )


def _inventory(root: Path, source_commit: str, base_commit: str) -> tuple[dict[str, str], list[str]]:
    _commit(root, source_commit)
    _commit(root, base_commit)
    _git(root, "merge-base", "--is-ancestor", base_commit, source_commit)
    tree = {}
    for row in _git(root, "ls-tree", "-rz", "--full-tree", source_commit).split(b"\0"):
        if row:
            meta, name = row.split(b"\t", 1)
            mode, kind, oid = meta.decode("ascii").split()
            tree[name.decode("utf-8")] = (mode, kind, oid)
    changed = {
        row.decode("utf-8") for row in _git(
            root, "diff", "--no-ext-diff", "--no-renames", "--name-only", "-z",
            base_commit, source_commit, "--",
        ).split(b"\0") if row
    }
    worktree_changes = {
        row.decode("utf-8") for row in _git(
            root, "diff", "--no-ext-diff", "--no-renames", "--name-only", "-z", source_commit, "--",
        ).split(b"\0") if row
    }
    if any(_protected(name) or _source_path(name) for name in worktree_changes):
        raise ValueError("uncommitted_production_changes")
    # Include ignored provider modules in this check: otherwise an ignored new
    # composition module could silently escape an apparently complete release.
    candidates = [
        *root.glob("bot/**/*.py"), *root.glob("scripts/**/*.py"), *root.glob("scripts/**/*.sh"),
        *root.glob("requirements*.txt"), *root.glob(".github/workflows/**/*"),
        *root.glob("k8s/**/*.yaml"), *root.glob("k8s/**/*.yml"), *root.glob("k8s/**/*.json"),
        *root.glob("Dockerfile*"), *(root / name for name in ROOT_RELEASE_FILES),
        *root.glob("*.py"), *root.glob("docker-compose*"),
    ]
    for path in candidates:
        if path.is_file() or path.is_symlink():
            name = path.relative_to(root).as_posix()
            if name not in tree and (_protected(name) or _source_path(name)):
                raise ValueError("uncommitted_production_source")
    selected = {
        name for name in set(tree) | changed
        if _protected(name) or name in changed and _source_path(name)
    }
    if (not {"bot/commissioning_gate.py", "bot/commissioning_runtime.py", "requirements.txt"} <= tree.keys()
            or not any(name.startswith(".github/workflows/") for name in tree)):
        raise ValueError("required_production_sources_missing")
    files = {}
    deleted = []
    for name in sorted(selected):
        path = root / name
        if name not in tree:
            if path.exists() or path.is_symlink():
                raise ValueError("deleted_source_present")
            deleted.append(name)
            continue
        mode, kind, oid = tree[name]
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("regular_committed_source_required")
        if int(_git(root, "cat-file", "-s", oid)) > MAX_SOURCE_BYTES:
            raise ValueError("committed_source_too_large")
        digest = _sha(_git(root, "cat-file", "blob", oid))
        if _sha(_regular_bytes(path, MAX_SOURCE_BYTES)) != digest:
            raise ValueError("checkout_does_not_match_commit")
        files[name] = digest
    return files, deleted


def build_manifest(
    repository: Path, *, source_commit: str, base_commit: str, image: str,
    previous_release: str, reviewed_bindings: dict[str, str],
) -> dict[str, Any]:
    """Bind committed source and caller references without inferring their authenticity."""
    root = Path(repository).absolute()
    if Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel")).strip()) != root:
        raise ValueError("repository_root_required")
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        raise ValueError("digest_pinned_image_required")
    if not isinstance(previous_release, str) or not IMAGE.fullmatch(previous_release):
        raise ValueError("digest_pinned_previous_release_required")
    if not isinstance(reviewed_bindings, dict) or set(reviewed_bindings) != BINDINGS:
        raise ValueError("all_external_binding_references_required")
    for digest in reviewed_bindings.values():
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("digest_only_binding_reference_required")
    files, deleted = _inventory(root, source_commit, base_commit)
    return {
        "format": FORMAT, "source_commit": source_commit, "base_commit": base_commit,
        "image": image, "previous_release": previous_release,
        "external_binding_references": dict(reviewed_bindings),
        "files_sha256": files, "deleted_files": deleted,
        "independent_approval_verified": False, "production_mutation_authorized": False,
    }


def _canonical(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def create_manifest(output: Path, repository: Path, **bindings: Any) -> str:
    """Create one owner-only manifest exclusively; never replace an existing path."""
    manifest = build_manifest(repository, **bindings)
    raw = _canonical(manifest)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest_too_large")
    output = Path(output).absolute()
    root = Path(repository).absolute()
    # A generated manifest cannot already be part of the source tree it attests.
    if output.is_relative_to(root):
        relative = output.relative_to(root).as_posix()
        if (_protected(relative) or _source_path(relative)
                or _git(root, "ls-tree", "-z", bindings["source_commit"], "--", relative)):
            raise ValueError("tracked_manifest_output_refused")
    for parent in output.parents:
        if parent.is_symlink():
            raise ValueError("symlink_output_parent_refused")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return _sha(raw)


def verify_manifest(
    manifest_path: Path, repository: Path, *, expected_sha256: str, source_commit: str,
) -> dict[str, Any]:
    """Verify a separately pinned manifest digest and reconstruct its exact source inventory."""
    if not isinstance(expected_sha256, str) or not HEX.fullmatch(expected_sha256):
        raise ValueError("external_manifest_digest_required")
    raw = _regular_bytes(Path(manifest_path).absolute(), MAX_MANIFEST_BYTES)
    if _sha(raw) != expected_sha256:
        raise ValueError("manifest_digest_mismatch")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("source_commit") != source_commit:
        raise ValueError("expected_source_commit_mismatch")
    expected = build_manifest(
        repository, source_commit=source_commit, base_commit=manifest.get("base_commit"),
        image=manifest.get("image"), previous_release=manifest.get("previous_release"),
        reviewed_bindings=manifest.get("external_binding_references"),
    )
    if raw != _canonical(expected):
        raise ValueError("manifest_content_mismatch")
    return expected


def main(argv: list[str] | None = None) -> int:
    """Run offline create or verify; return fixed non-sensitive failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create")
    verify = actions.add_parser("verify")
    for command in (create, verify):
        command.add_argument("--repository", type=Path, default=Path.cwd())
        command.add_argument("--source-commit", required=True)
        command.add_argument("--manifest", type=Path, required=True)
    create.add_argument("--base-commit", required=True)
    create.add_argument("--image", required=True)
    create.add_argument("--previous-release", required=True)
    create.add_argument("--reviewed-binding", action="append", required=True, metavar="NAME=sha256:DIGEST")
    verify.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "create":
            references = {}
            for value in args.reviewed_binding:
                name, separator, digest = value.partition("=")
                if not separator or name in references:
                    raise ValueError("invalid_or_duplicate_binding")
                references[name] = digest
            digest = create_manifest(
                args.manifest, args.repository, source_commit=args.source_commit,
                base_commit=args.base_commit, image=args.image, previous_release=args.previous_release,
                reviewed_bindings=references,
            )
        else:
            verify_manifest(args.manifest, args.repository, expected_sha256=args.expected_sha256,
                            source_commit=args.source_commit)
            digest = args.expected_sha256
        print(json.dumps({"status": "verified_offline", "manifest_sha256": digest,
                          "production_mutation_authorized": False}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, UnicodeError):
        print('{"status":"FAILED_CLOSED","production_mutation_authorized":false}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
