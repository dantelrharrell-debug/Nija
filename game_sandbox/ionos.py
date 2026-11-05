"""Canonical boundary for the 72-decision game recovered from NIJA's served build."""

from __future__ import annotations

import hashlib
import json
import shutil
# The original JS engine uses a fixed executable/script without a shell.
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from .service import Denied, Manifest
from .ionos_source import REPORT_MODULE_SHA256, SOURCE_SHA256

ROOT = Path(__file__).resolve().parent


class PublishedGame(Manifest):
    """Preserve actions, stop-loss state, difficulty and daily seed for all 72 decisions."""

    def __init__(self) -> None:
        content = (ROOT / "ionos_published_report.mjs").read_bytes()
        if hashlib.sha256(content).hexdigest() != REPORT_MODULE_SHA256:
            raise Denied("canonical_module_integrity_mismatch")
        super().__init__(
            {
                "version": "ionos-served-iq72-" + SOURCE_SHA256[:16],
                "source_sha256": SOURCE_SHA256,
                "structure": "12_per_challenge",
                "challenges": [
                    {"rounds": [{"id": f"challenge_{i}_round_{j}", "choices": 6} for j in range(12)]} for i in range(6)
                ],
            }
        )

    def answers(self, payload: Any) -> str:
        """Validate the actual IONOS run, never synthetic multiple-choice answers."""
        if (
            not isinstance(payload, dict)
            or set(payload) != {"mode", "level", "dayNum", "challenges"}
            or payload["mode"] not in ("standard", "daily")
            or payload["level"] not in ("beginner", "intermediate", "advanced")
            or type(payload["dayNum"]) is not int
            or not 0 <= payload["dayNum"] <= 1_000_000
            or (payload["mode"] == "standard" and payload["dayNum"] != 0)
            or not isinstance(payload["challenges"], list)
            or len(payload["challenges"]) != 6
        ):
            raise Denied("canonical_72_decision_run_required")
        for challenge in payload["challenges"]:
            if not isinstance(challenge, list) or len(challenge) != 12:
                raise Denied("twelve_rounds_in_each_of_six_challenges_required")
            for decision in challenge:
                if (
                    not isinstance(decision, dict)
                    or set(decision) != {"action", "stop"}
                    or decision["action"] not in ("buy", "sell", "hold")
                    or type(decision["stop"]) is not bool
                ):
                    raise Denied("invalid_action_or_stop")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_published_report(payload: dict) -> dict:
    """Call the original report implementation, including its script-free HTML export."""
    game = PublishedGame()
    encoded = game.answers(payload)
    node_path = shutil.which("node")
    if not node_path:
        raise Denied("node_runtime_required")
    try:
        # Fixed absolute executable/script; validated JSON goes only through stdin.
        result = subprocess.run(  # nosec B603
            [node_path, str(ROOT / "ionos_runner.mjs")],
            input=encoded,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            shell=False,
            env={"PATH": str(Path(node_path).parent)},
        )
        response = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise Denied("original_report_unavailable") from error
    report = response["report"]
    if len(report["challenges"]) != 6 or sum(len(c["decisions"]) for c in report["challenges"]) != 72:
        raise Denied("report_history_mismatch")
    return response
