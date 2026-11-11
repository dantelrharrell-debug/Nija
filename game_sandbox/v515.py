"""Use approved v515 decisions and scoring inside the existing sandbox boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess  # nosec B404 - fixed local Node adapter, no shell

from .ionos import PublishedGame
from .service import Denied, Manifest

ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT.parent / "web" / "trading-challenge" / "v515" / "offline_tiq_premium"
SOURCE_SHA256 = "77079538953000d0ebbd741665c081820de3a8c6f60debc0cb6c72502f99d224"  # pragma: allowlist secret - approved archive checksum
MODULE_DIGESTS = {
    "tiq_report.mjs": "a669a0ca2a70b3aa5536a0a0b7478e03b02b544dc2c2f7077c13c194e790b876",  # pragma: allowlist secret - public source checksum
    "tiq_engine.mjs": "6a05c0e1231fb5f4a9a0f3f88604150d138f977bc20c7956d421dd2be38a5ccc",  # pragma: allowlist secret - public source checksum
    "tiq_scoring.mjs": "2a4593bb379ec22c136069d9013273101204052a6293de0cc2ecca7404fcde9f",  # pragma: allowlist secret - public source checksum
}


class V515Game(PublishedGame):
    """Reuse strict 72-decision validation with a distinct v515 manifest identity."""

    def __init__(self) -> None:
        for name, expected in MODULE_DIGESTS.items():
            target = SOURCE_ROOT / name
            if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise Denied("v515_source_integrity_mismatch")
        Manifest.__init__(self, {
            "version": "ionos-v515-iq72-" + SOURCE_SHA256[:16] + "-copy1",
            "source_sha256": SOURCE_SHA256,
            "derived_report_sha256": MODULE_DIGESTS["tiq_report.mjs"],
            "structure": "12_per_challenge",
            "challenges": [
                {"rounds": [{"id": f"challenge_{i}_round_{j}", "choices": 6} for j in range(12)]}
                for i in range(6)
            ],
        })


def build_v515_report(payload: dict) -> dict:
    """Generate the pinned v515 report-copy revision after entitlement verification."""
    encoded = V515Game().answers(payload)
    node_path = shutil.which("node")
    if not node_path:
        raise Denied("node_runtime_required")
    try:
        result = subprocess.run(  # nosec B603 - fixed adapter; validated answers only through stdin
            [node_path, str(ROOT / "v515_runner.mjs")], input=encoded,
            capture_output=True, text=True, timeout=10, check=True, shell=False,
            env={"PATH": str(Path(node_path).parent)},
        )
        response = json.loads(result.stdout)
        report = response["report"]
        if len(report["challenges"]) != 6 or any(len(c["decisions"]) != 12 for c in report["challenges"]):
            raise ValueError("invalid_report_history")
        if "<script" in response["download_html"].lower():
            raise ValueError("active_report_content")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
        raise Denied("v515_report_unavailable") from error
    return response
