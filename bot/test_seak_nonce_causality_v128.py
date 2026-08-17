from pathlib import Path
from unittest import mock

import bot.seak_nonce_causality_v128_patch as patch


def test_v128_installs_after_v127():
    source = Path(__file__).with_name("bot.py").read_text(encoding="utf-8")
    v127 = source.index("CANONICAL_PUBLICATION_DIRECT_V127")
    v128 = source.index("SEAK_NONCE_CAUSALITY_V128")
    assert v128 > v127


def test_v128_never_resumes_seak_or_grants_authority():
    source = Path(patch.__file__).read_text(encoding="utf-8")
    assert ".resume(" not in source
    assert "mark_ready(" not in source
    assert 'NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"' not in source
    assert "NIJA_EXECUTION_ACTIVE" not in source
    assert "nonce_bypass=false" in source
    assert "seak_auto_resume=false" in source


def test_nonce_drift_filter_requires_explicit_seak_causality_and_live_halt():
    with mock.patch.object(patch, "_seak_halted", return_value=(True, "test_halt")):
        assert patch._seak_caused_nonce_detail(
            "LIVE TRADING BLOCKED last_error=SEAK halt active"
        )
        assert not patch._seak_caused_nonce_detail("nonce lease unstable")

    with mock.patch.object(patch, "_seak_halted", return_value=(False, "")):
        assert not patch._seak_caused_nonce_detail(
            "LIVE TRADING BLOCKED last_error=SEAK halt active"
        )


def test_release_and_marker_are_v128():
    assert patch.MARKER == "20260816-seak-nonce-causality-v128"
    assert patch.RELEASE_ID == "20260816-runtime-convergence-v128"
