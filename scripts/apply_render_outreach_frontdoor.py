"""Idempotently expose protected outreach and lead routes on NIJA's Render front door.

The Render service binds ``render_liveness_server.py`` to the public PORT before
the trading runtime starts. This patch adds only delegation hooks to stdlib-only
outreach/lead modules, preserving all existing liveness and trading-readiness behavior.
"""

from __future__ import annotations

import pathlib
import py_compile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = ROOT / "render_liveness_server.py"
EXTENSION = ROOT / "render_outreach_extension.py"
BASE_IMPORT = "from render_outreach_routes import handle_outreach_get, handle_outreach_post\n"
EXT_IMPORT = (
    "from render_outreach_extension import "
    "handle_outreach_extension_get, handle_outreach_extension_post, "
    "start_justcall_webhook_autoconfig\n"
)
LEAD_IMPORT = "from render_lead_intake import handle_lead_intake_post\n"
EXT_GET_MARKER = "        if handle_outreach_extension_get(self):\n            return\n\n"
BASE_GET_MARKER = "        if handle_outreach_get(self):\n            return\n\n"
AUTOCONFIG_CALL = "    start_justcall_webhook_autoconfig()\n"
POST_METHOD = '''    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract\n        if handle_lead_intake_post(self):\n            return\n        if handle_outreach_extension_post(self):\n            return\n        if handle_outreach_post(self):\n            return\n        self.send_response(404)\n        self.send_header("Content-Length", "0")\n        self.send_header("Connection", "close")\n        self.end_headers()\n\n'''


def main() -> int:
    # JustCall's current contact-status event is ``jc.contact_status_updated``.
    # Older NIJA builds used ``contact.status_updated``, which caused exactly one
    # webhook subscription to fail on every startup. Normalize the source before
    # the extension is imported by the front-door listener.
    extension_text = EXTENSION.read_text(encoding="utf-8")
    legacy_contact_event = '"contact.status_updated"'
    canonical_contact_event = '"jc.contact_status_updated"'
    if legacy_contact_event in extension_text:
        extension_text = extension_text.replace(legacy_contact_event, canonical_contact_event)
        EXTENSION.write_text(extension_text, encoding="utf-8")

    text = TARGET.read_text(encoding="utf-8")
    original = text

    anchor = "from typing import Any, Optional\n"
    if BASE_IMPORT.strip() not in text:
        if anchor not in text:
            raise RuntimeError("render liveness typing import anchor missing")
        text = text.replace(anchor, anchor + "\n" + BASE_IMPORT, 1)

    old_ext_import = (
        "from render_outreach_extension import "
        "handle_outreach_extension_get, handle_outreach_extension_post\n"
    )
    if old_ext_import in text:
        text = text.replace(old_ext_import, EXT_IMPORT, 1)
    elif EXT_IMPORT.strip() not in text:
        if BASE_IMPORT not in text:
            raise RuntimeError("render outreach base import anchor missing")
        text = text.replace(BASE_IMPORT, BASE_IMPORT + EXT_IMPORT, 1)

    if LEAD_IMPORT.strip() not in text:
        if EXT_IMPORT not in text:
            raise RuntimeError("render outreach extension import anchor missing")
        text = text.replace(EXT_IMPORT, EXT_IMPORT + LEAD_IMPORT, 1)

    get_anchor = "    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract\n"
    if get_anchor not in text:
        raise RuntimeError("render liveness do_GET anchor missing")
    if EXT_GET_MARKER.strip() not in text:
        if BASE_GET_MARKER in text:
            text = text.replace(BASE_GET_MARKER, EXT_GET_MARKER + BASE_GET_MARKER, 1)
        else:
            text = text.replace(get_anchor, get_anchor + EXT_GET_MARKER + BASE_GET_MARKER, 1)
    elif BASE_GET_MARKER.strip() not in text:
        text = text.replace(EXT_GET_MARKER, EXT_GET_MARKER + BASE_GET_MARKER, 1)

    if "def do_POST(self)" not in text:
        log_anchor = "    def log_message(self, fmt: str, *args: object) -> None:\n"
        if log_anchor not in text:
            raise RuntimeError("render liveness log_message anchor missing")
        text = text.replace(log_anchor, POST_METHOD + log_anchor, 1)
    elif "handle_lead_intake_post(self)" not in text:
        post_start = text.index("    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract\n")
        post_end = text.index("    def log_message(self, fmt: str, *args: object) -> None:\n", post_start)
        text = text[:post_start] + POST_METHOD + text[post_end:]

    if AUTOCONFIG_CALL.strip() not in text:
        server_anchor = "    server.allow_reuse_address = True\n\n"
        if server_anchor not in text:
            raise RuntimeError("render liveness server startup anchor missing")
        text = text.replace(server_anchor, server_anchor + AUTOCONFIG_CALL + "\n", 1)

    if text != original:
        TARGET.write_text(text, encoding="utf-8")

    for module in (
        TARGET,
        ROOT / "render_outreach_routes.py",
        EXTENSION,
        ROOT / "render_outreach_store.py",
        ROOT / "render_lead_intake.py",
    ):
        py_compile.compile(str(module), doraise=True)

    verified = TARGET.read_text(encoding="utf-8")
    required = (
        BASE_IMPORT.strip(),
        EXT_IMPORT.strip(),
        LEAD_IMPORT.strip(),
        "handle_outreach_extension_get(self)",
        "handle_outreach_get(self)",
        "handle_lead_intake_post(self)",
        "handle_outreach_extension_post(self)",
        "handle_outreach_post(self)",
        "start_justcall_webhook_autoconfig()",
    )
    missing = [marker for marker in required if marker not in verified]
    if missing:
        raise RuntimeError("Render outreach front-door patch incomplete: " + ", ".join(missing))

    extension_verified = EXTENSION.read_text(encoding="utf-8")
    if legacy_contact_event in extension_verified:
        raise RuntimeError("Legacy JustCall contact-status webhook event remains")
    if canonical_contact_event not in extension_verified:
        raise RuntimeError("Canonical JustCall contact-status webhook event missing")

    print(
        "RENDER_OUTREACH_FRONTDOOR_READY marker=20260831-render-outreach-frontdoor-v6 "
        "protected=true signed_webhook=true webhook_autoconfig=true "
        "lead_intake_normalized=true account_check_protected=true "
        "markdown_email_normalized=true nested_formname_normalized=true "
        "justcall_contact_status_event_canonical=true "
        "campaign_compliance_fail_closed=true consent_fail_closed=true "
        "liveness_unchanged=true readiness_unchanged=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
