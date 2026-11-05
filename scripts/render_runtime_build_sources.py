"""Reproduce reviewed Docker source rewrites without executing Git-supplied code.

Approval pins remain hashes of original Git bytes. Runtime pins are derived
separately using only the fixed, locally reviewed transformations below. This
does not attest the container image or grant deployment/trading authorization.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
from pathlib import Path

from scripts import apply_canonical_launcher_v26 as canonical
from scripts import apply_render_signal_forwarding_v262 as signals
from scripts import apply_startup_handoff_fix as startup
from scripts.nija_kraken_instance_diagnostic import SOURCE_PATHS

# Both Dockerfiles have the same rewrite sequence. The second only adds
# --no-install-recommends to apt-get. Any other recipe requires code review.
DOCKER_SHA256 = frozenset({
    "dba35727604358caa0bfd5df1ed2262e331fd34103e526d85d6c02d273ef5827",  # pragma: allowlist secret
    "087f5985aaa5a31f98b9f68422370d93241204a9eb49171b8d63ae0c62df5fb4",  # pragma: allowlist secret
})
RECIPE_SHA256 = {
    "scripts/install_sitecustomize_defer_guard.py":
        "da58660cd14c3887a0b5b81f4742aea9f5ec8f7a9ef78ca2aa9d82da04af44e3",  # pragma: allowlist secret
    "apply_bot_package_defer_fix.py":
        "b80c4bb8d6dcad9d675027fd7d39b764d7f5f9e1e5abd1788e01691adcd581f8",  # pragma: allowlist secret
    "scripts/apply_startup_handoff_fix.py":
        "3fd197b4c66814d192342b805df0f5888712311a181a080c19d55a0c0b6f3341",  # pragma: allowlist secret
    "scripts/apply_canonical_launcher_v26.py":
        "344bfa73e0472b372cd494153dcd3bebc494100de3597359e28bdf95da87c18b",  # pragma: allowlist secret
    "scripts/apply_writer_generation_handoff_v45.py":
        "12b93448d0c32dcba715a5b31f534d20dbb7e5bb311006fac889323d085a0f00",  # pragma: allowlist secret
    "scripts/apply_render_signal_forwarding_v262.py":
        "ed4497b356a8e68c9918380912d4805a1522e47174964eee2f93472aefc5c413",  # pragma: allowlist secret
}
RECIPE_PATHS = ("Dockerfile", *RECIPE_SHA256)


class BuildRecipeDenied(ValueError):
    """A fixed, non-secret failure reason for unsupported build inputs."""


class _MemoryText:
    """Supply the existing signal patch's text interface entirely in memory."""

    def __init__(self, text: str) -> None:
        self.text = text

    def read_text(self, *, encoding: str) -> str:
        return self.text

    def write_text(self, text: str, *, encoding: str) -> None:
        self.text = text


def derive_runtime_source_sha256(sources: dict[str, bytes], recipe: dict[str, bytes]) -> dict[str, str]:
    """Derive exact runtime bytes only for the reviewed, hash-pinned recipe.

    Non-target rewrites affect site-packages, bot/__init__.py, the launcher,
    startup_position_sync.py and prebootstrap, none of which are SOURCE_PATHS. Never
    import or execute a module read from the inspected commit.
    """
    if set(sources) != set(SOURCE_PATHS) or set(recipe) != set(RECIPE_PATHS):
        raise BuildRecipeDenied("runtime_build_inputs_incomplete")
    if hashlib.sha256(recipe["Dockerfile"]).hexdigest() not in DOCKER_SHA256:
        raise BuildRecipeDenied("runtime_build_recipe_unreviewed")
    for path, digest in RECIPE_SHA256.items():
        if hashlib.sha256(recipe[path]).hexdigest() != digest:
            raise BuildRecipeDenied("runtime_build_recipe_unreviewed")
    # A newer verification checkout must not silently change the derivation.
    root = Path(__file__).resolve().parents[1]
    for module in (startup, canonical, signals):
        path = Path(module.__file__).resolve()
        relative = path.relative_to(root).as_posix()
        if hashlib.sha256(path.read_bytes()).hexdigest() != RECIPE_SHA256[relative]:
            raise BuildRecipeDenied("runtime_build_verifier_recipe_changed")
    try:
        built = dict(sources)
        start = _MemoryText(canonical.patch_text(startup.patch_text(sources["start.sh"].decode("utf-8"))))
        with redirect_stdout(io.StringIO()):
            signals.apply(start)
        built["start.sh"] = start.text.encode("utf-8")
        built["bot/broker_manager.py"] = canonical.patch_broker_manager_text(
            sources["bot/broker_manager.py"].decode("utf-8"),
        ).encode("utf-8")
    except (UnicodeError, RuntimeError, ValueError):
        raise BuildRecipeDenied("runtime_build_transform_failed") from None
    return {path: hashlib.sha256(data).hexdigest() for path, data in built.items()}
