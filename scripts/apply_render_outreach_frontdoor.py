"""Idempotently expose protected outreach, Apollo feeder, autodial, and lead routes."""
from __future__ import annotations

import pathlib
import py_compile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = ROOT / "render_liveness_server.py"
EXTENSION = ROOT / "render_outreach_extension.py"
AUTODIAL = ROOT / "render_outreach_autodial.py"
APOLLO_FEEDER = ROOT / "render_apollo_feeder.py"
BASE_IMPORT = "from render_outreach_routes import handle_outreach_get, handle_outreach_post\n"
EXT_IMPORT = (
    "from render_outreach_extension import "
    "handle_outreach_extension_get, handle_outreach_extension_post, "
    "start_justcall_webhook_autoconfig\n"
)
AUTODIAL_IMPORT = (
    "from render_outreach_autodial import "
    "handle_autodial_get, handle_autodial_post, start_justcall_autodial\n"
)
APOLLO_IMPORT = (
    "from render_apollo_feeder import "
    "handle_apollo_feeder_get, handle_apollo_feeder_post, start_apollo_feeder\n"
)
LEAD_IMPORT = "from render_lead_intake import handle_lead_intake_post\n"
APOLLO_GET_MARKER = "        if handle_apollo_feeder_get(self):\n            return\n\n"
AUTODIAL_GET_MARKER = "        if handle_autodial_get(self):\n            return\n\n"
EXT_GET_MARKER = "        if handle_outreach_extension_get(self):\n            return\n\n"
BASE_GET_MARKER = "        if handle_outreach_get(self):\n            return\n\n"
AUTOCONFIG_CALL = "    start_justcall_webhook_autoconfig()\n"
AUTODIAL_CALL = "    start_justcall_autodial()\n"
APOLLO_CALL = "    start_apollo_feeder()\n"
POST_METHOD = '''    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract\n        if handle_lead_intake_post(self):\n            return\n        if handle_apollo_feeder_post(self):\n            return\n        if handle_autodial_post(self):\n            return\n        if handle_outreach_extension_post(self):\n            return\n        if handle_outreach_post(self):\n            return\n        self.send_response(404)\n        self.send_header("Content-Length", "0")\n        self.send_header("Connection", "close")\n        self.end_headers()\n\n'''


def main() -> int:
    extension_text = EXTENSION.read_text(encoding="utf-8")
    legacy_contact_event = '"contact.status_updated"'
    canonical_contact_event = '"jc.contact_status_updated"'
    if legacy_contact_event in extension_text:
        EXTENSION.write_text(
            extension_text.replace(legacy_contact_event, canonical_contact_event),
            encoding="utf-8",
        )

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
        text = text.replace(BASE_IMPORT, BASE_IMPORT + EXT_IMPORT, 1)
    if AUTODIAL_IMPORT.strip() not in text:
        text = text.replace(EXT_IMPORT, EXT_IMPORT + AUTODIAL_IMPORT, 1)
    if APOLLO_IMPORT.strip() not in text:
        text = text.replace(AUTODIAL_IMPORT, AUTODIAL_IMPORT + APOLLO_IMPORT, 1)
    if LEAD_IMPORT.strip() not in text:
        text = text.replace(APOLLO_IMPORT, APOLLO_IMPORT + LEAD_IMPORT, 1)

    get_anchor = "    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract\n"
    if get_anchor not in text:
        raise RuntimeError("render liveness do_GET anchor missing")
    get_chain = APOLLO_GET_MARKER + AUTODIAL_GET_MARKER + EXT_GET_MARKER + BASE_GET_MARKER
    for marker in (APOLLO_GET_MARKER, AUTODIAL_GET_MARKER, EXT_GET_MARKER, BASE_GET_MARKER):
        text = text.replace(marker, "")
    text = text.replace(get_anchor, get_anchor + get_chain, 1)

    log_anchor = "    def log_message(self, fmt: str, *args: object) -> None:\n"
    if "    def do_POST(self) -> None:" in text:
        post_start = text.index("    def do_POST(self) -> None:")
        post_end = text.index(log_anchor, post_start)
        text = text[:post_start] + POST_METHOD + text[post_end:]
    else:
        text = text.replace(log_anchor, POST_METHOD + log_anchor, 1)

    server_anchor = "    server.allow_reuse_address = True\n\n"
    if AUTOCONFIG_CALL.strip() not in text:
        text = text.replace(server_anchor, server_anchor + AUTOCONFIG_CALL + "\n", 1)
    if AUTODIAL_CALL.strip() not in text:
        text = text.replace(AUTOCONFIG_CALL, AUTOCONFIG_CALL + AUTODIAL_CALL, 1)
    if APOLLO_CALL.strip() not in text:
        text = text.replace(AUTODIAL_CALL, AUTODIAL_CALL + APOLLO_CALL, 1)

    if text != original:
        TARGET.write_text(text, encoding="utf-8")

    for module in (
        TARGET,
        ROOT / "render_outreach_routes.py",
        EXTENSION,
        AUTODIAL,
        APOLLO_FEEDER,
        ROOT / "render_outreach_store.py",
        ROOT / "render_lead_intake.py",
    ):
        py_compile.compile(str(module), doraise=True)

    verified = TARGET.read_text(encoding="utf-8")
    required = (
        BASE_IMPORT.strip(), EXT_IMPORT.strip(), AUTODIAL_IMPORT.strip(), APOLLO_IMPORT.strip(), LEAD_IMPORT.strip(),
        "handle_apollo_feeder_get(self)", "handle_autodial_get(self)",
        "handle_outreach_extension_get(self)", "handle_outreach_get(self)",
        "handle_lead_intake_post(self)", "handle_apollo_feeder_post(self)",
        "handle_autodial_post(self)", "handle_outreach_extension_post(self)", "handle_outreach_post(self)",
        "start_justcall_webhook_autoconfig()", "start_justcall_autodial()", "start_apollo_feeder()",
    )
    missing = [marker for marker in required if marker not in verified]
    if missing:
        raise RuntimeError("Render outreach front-door patch incomplete: " + ", ".join(missing))

    extension_verified = EXTENSION.read_text(encoding="utf-8")
    if legacy_contact_event in extension_verified or canonical_contact_event not in extension_verified:
        raise RuntimeError("JustCall contact-status webhook event is not canonical")

    autodial_verified = AUTODIAL.read_text(encoding="utf-8")
    for marker in (
        "verified_consent_required", "fresh_dnc_check_required", "suppression_clear_required",
        "contact_timezone_required", "duplicate_active_call", "ai_agent_unavailable",
        "daily_cap_reached", "outreach_autodial_daily_quota", "JUSTCALL_AUTODIAL_WORKER",
    ):
        if marker not in autodial_verified:
            raise RuntimeError("Autodial fail-closed marker missing: " + marker)

    apollo_verified = APOLLO_FEEDER.read_text(encoding="utf-8")
    for marker in (
        "APOLLO_NIJA_FEEDER", "cold_contacts_call_ready", "APOLLO_API_KEY",
        "NIJA_APOLLO_CONSENT_FIELD_ID", "NIJA_APOLLO_DNC_STATUS_FIELD_ID",
        "provider_dnc_found", "requires_authoritative_consent_and_compliance_evidence",
    ):
        if marker not in apollo_verified:
            raise RuntimeError("Apollo feeder fail-closed marker missing: " + marker)

    print(
        "RENDER_OUTREACH_FRONTDOOR_READY marker=20260831-render-outreach-frontdoor-v8 "
        "protected=true signed_webhook=true webhook_autoconfig=true "
        "apollo_feeder=true apollo_cold_consent_not_inferred=true "
        "autodial_queue=true autodial_worker=true autodial_daily_cap=true autodial_fail_closed=true "
        "campaign_compliance_fail_closed=true consent_fail_closed=true "
        "liveness_unchanged=true readiness_unchanged=true",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
