"""Apply canonical activation-publication convergence fast-path v376.

Production startup can transiently fail the late runtime release-manifest audit
before module identity converges.  When that happens, the already-shipped
v134/v135/v136 activation safety chain is skipped for the process lifetime and
the legacy v63 activation snapshot bridge can remain the active commit wrapper.

v376 does not implement new activation semantics.  It only makes the existing
fail-closed v134 -> v135 -> v136 installers part of bot.py's canonical fast-path
installer list, immediately after v131.  Those patches preserve kill switch,
writer/nonce, risk, execution-proof, capital-freshness, and position gates and
v136 explicitly removes the legacy secondary force-transition fallback.

No state is forced, no proof is fabricated, no freshness window is extended,
and no order is submitted by this source patcher.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_PATH = ROOT / "bot" / "bot.py"
MARKER = "20260907-activation-publication-fast-path-v376"

_INSERT = '''    ("bot.readiness_proof_convergence_v134_patch", "READINESS_PROOF_CONVERGENCE_V134"),\n    ("bot.activation_stop_capital_freshness_v135_patch", "ACTIVATION_STOP_CAPITAL_FRESHNESS_V135"),\n    ("bot.activation_publication_convergence_v136_patch", "ACTIVATION_PUBLICATION_CONVERGENCE_V136"),\n'''
_ANCHOR = '    ("bot.readiness_killswitch_causality_v131_patch", "READINESS_KILLSWITCH_CAUSALITY_V131"),\n'


def patch_bot_text(text: str) -> str:
    if "ACTIVATION_PUBLICATION_CONVERGENCE_V136" in text and "READINESS_PROOF_CONVERGENCE_V134" in text:
        return text
    if _ANCHOR not in text:
        raise RuntimeError("v376 canonical fast-path anchor missing")
    patched = text.replace(_ANCHOR, _ANCHOR + _INSERT, 1)
    for token in (
        "READINESS_PROOF_CONVERGENCE_V134",
        "ACTIVATION_STOP_CAPITAL_FRESHNESS_V135",
        "ACTIVATION_PUBLICATION_CONVERGENCE_V136",
    ):
        if token not in patched:
            raise RuntimeError(f"v376 insertion verification failed: {token}")
    return patched


def main() -> None:
    original = BOT_PATH.read_text(encoding="utf-8")
    patched = patch_bot_text(original)
    if patched != original:
        BOT_PATH.write_text(patched, encoding="utf-8")
    print(
        "ACTIVATION_PUBLICATION_FAST_PATH_V376_APPLIED "
        f"marker={MARKER} existing_v134_v135_v136_only=true "
        "force_activation=false freshness_extended=false proof_fabricated=false "
        "order_submitted=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
