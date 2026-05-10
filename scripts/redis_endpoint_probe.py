#!/usr/bin/env python3
"""Probe Redis endpoint resolution and report which candidate wins."""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

from bot.redis_env import get_all_redis_urls
from bot.redis_runtime import connect_redis_with_fallback


def _redact(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = parsed.hostname or "<unknown-host>"
    try:
        port = parsed.port
    except ValueError:
        port = None
    return f"{parsed.scheme}://***@{host}:{port or '<unknown-port>'}"


def _print_candidate_matrix(primary_url: str) -> None:
    print("Configured Redis URL candidates (priority order):")
    configured = get_all_redis_urls()
    if not configured:
        print("  - none")
        return

    for source, url in configured:
        marker = "PRIMARY" if url.strip() == primary_url.strip() else "ALT"
        print(f"  - [{marker}] source={source} target={_redact(url)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Redis connectivity and report fallback winner")
    parser.add_argument("--url", dest="redis_url", default="", help="Optional explicit redis URL")
    parser.add_argument("--retries", type=int, default=2, help="Retry attempts per candidate")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between retries")
    parser.add_argument(
        "--decode-responses",
        action="store_true",
        help="Initialize client with decode_responses=True",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    primary_url = (args.redis_url or os.getenv("NIJA_REDIS_URL", "")).strip()
    if not primary_url:
        all_urls = get_all_redis_urls()
        primary_url = all_urls[0][1] if all_urls else ""

    if not primary_url:
        print("ERROR: No Redis URL configured.")
        print("Checked URL sources: NIJA_REDIS_URL, REDIS_TLS_URL, REDIS_URL, REDIS_PRIVATE_URL, REDIS_PUBLIC_URL")
        return 2

    print(f"Primary Redis candidate: {_redact(primary_url)}")
    _print_candidate_matrix(primary_url)

    probe_logs: list[str] = []

    def _capture(msg: str) -> None:
        probe_logs.append(msg)
        print(f"probe> {msg}")

    try:
        client, selected_url = connect_redis_with_fallback(
            url=primary_url,
            decode_responses=args.decode_responses,
            retries=max(1, int(args.retries)),
            delay_s=max(0.0, float(args.delay)),
            log=_capture,
        )
        try:
            pong = client.ping()
        finally:
            client.close()

        selected_host = (urlparse(selected_url).hostname or "").lower()
        selected_scheme = (urlparse(selected_url).scheme or "").lower()
        is_proxy = selected_host.endswith(".proxy.rlwy.net")

        print("RESULT: Redis connectivity OK")
        print(f"Selected endpoint: {_redact(selected_url)}")
        print(f"Selected host class: {'railway-proxy' if is_proxy else 'internal-or-native'}")
        print(f"Selected TLS scheme: {selected_scheme}")
        print(f"Ping response: {pong}")

        if is_proxy and selected_scheme == "rediss":
            print("CONCLUSION: Railway proxy TLS is working on the selected proxy port.")
        elif is_proxy and selected_scheme != "rediss":
            print("CONCLUSION: Connected via Railway proxy without TLS (operator override/fallback).")
        else:
            print("CONCLUSION: Proxy TLS path was not selected; using internal/native fallback endpoint.")

        return 0
    except Exception as exc:
        print(f"RESULT: Redis connectivity FAILED: {exc}")
        if probe_logs:
            print("Last probe events:")
            for line in probe_logs[-6:]:
                print(f"  - {line}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
