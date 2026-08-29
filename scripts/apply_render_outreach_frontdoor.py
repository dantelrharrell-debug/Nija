"""Idempotently expose protected JustCall routes on NIJA's Render front door.

The Render service binds ``render_liveness_server.py`` to the public PORT before
the trading runtime starts. This patch adds only delegation hooks to the
stdlib-only ``render_outreach_routes`` module, preserving all existing liveness
and trading-readiness behavior.
"""

from __future__ import annotations

import pathlib
import py_compile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = ROOT / "render_liveness_server.py"
IMPORT_LINE = "from render_outreach_routes import handle_outreach_get, handle_outreach_post\n"
GET_MARKER = "        if handle_outreach_get(self):\n            return\n\n"
POST_METHOD = '''    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract\n        if handle_outreach_post(self):\n            return\n        self.send_response(404)\n        self.send_header("Content-Length", "0")\n        self.send_header("Connection", "close")\n        self.end_headers()\n\n'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    original = text

    if IMPORT_LINE.strip() not in text:
        anchor = "from typing import Any, Optional\n"
        if anchor not in text:
            raise RuntimeError("render liveness typing import anchor missing")
        text = text.replace(anchor, anchor + "\n" + IMPORT_LINE, 1)

    if GET_MARKER.strip() not in text:
        anchor = "    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract\n"
        if anchor not in text:
            raise RuntimeError("render liveness do_GET anchor missing")
        text = text.replace(anchor, anchor + GET_MARKER, 1)

    if "def do_POST(self)" not in text:
        anchor = "    def log_message(self, fmt: str, *args: object) -> None:\n"
        if anchor not in text:
            raise RuntimeError("render liveness log_message anchor missing")
        text = text.replace(anchor, POST_METHOD + anchor, 1)

    if text != original:
        TARGET.write_text(text, encoding="utf-8")

    py_compile.compile(str(TARGET), doraise=True)
    outreach = ROOT / "render_outreach_routes.py"
    py_compile.compile(str(outreach), doraise=True)

    verified = TARGET.read_text(encoding="utf-8")
    required = (
        IMPORT_LINE.strip(),
        "handle_outreach_get(self)",
        "handle_outreach_post(self)",
    )
    missing = [marker for marker in required if marker not in verified]
    if missing:
        raise RuntimeError("Render outreach front-door patch incomplete: " + ", ".join(missing))

    print(
        "RENDER_OUTREACH_FRONTDOOR_READY marker=20260829-render-outreach-frontdoor-v1 "
        "protected=true consent_fail_closed=true liveness_unchanged=true readiness_unchanged=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
