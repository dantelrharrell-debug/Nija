#!/usr/bin/env python3
"""Generate Capacitor's root HTML entrypoint from NIJA's checked-in web template.

This does not create native iOS/Android projects, authorize live trading,
configure API secrets, or certify a store-ready application.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "frontend" / "templates" / "index.html"
ENTRYPOINT = ROOT / "frontend" / "index.html"
STATIC = ROOT / "frontend" / "static"


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.paths.append(value)


def compile_entrypoint(template: str, static_root: Path) -> str:
    if "{{" in template or "{%" in template:
        raise ValueError("Server-side template syntax cannot be bundled directly")
    # The source template is served from /templates/; the generated entrypoint
    # lives one directory higher. Its static URLs must be adjusted accordingly.
    compiled = template.replace("../static/", "static/")
    if "../static/" in compiled:
        raise ValueError("Unresolved relative static asset path")
    refs = AssetReferences()
    refs.feed(compiled)
    missing = []
    for ref in refs.paths:
        url = urlsplit(ref)
        if url.scheme or url.netloc or not url.path or url.path == "#":
            continue
        # Validate only packaged local static references; runtime links are
        # validated by app/device tests, not the bundle generator.
        path = url.path.lstrip("/")
        if path.startswith("static/"):
            relative = Path(path[len("static/"):])
            if ".." in relative.parts or not (static_root / relative).is_file():
                missing.append(ref)
    if missing:
        raise ValueError("Missing bundled assets: " + ", ".join(sorted(set(missing))))
    if not re.search(r"<html\b", compiled, re.IGNORECASE):
        raise ValueError("Mobile entrypoint has no HTML document")
    return compiled


def main() -> int:
    compiled = compile_entrypoint(TEMPLATE.read_text(encoding="utf-8"), STATIC)
    ENTRYPOINT.write_text(compiled, encoding="utf-8")
    print(f"MOBILE_WEB_ENTRYPOINT_OK: {ENTRYPOINT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
