#!/usr/bin/env python3
"""Probe Redis endpoint resolution and report which candidate wins."""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from urllib.parse import urlparse

# Ensure repo root is importable when this script is invoked directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from bot.redis_env import get_all_redis_urls
except ModuleNotFoundError:
    # Fallback for shells/interpreters that fail package resolution.
    redis_env_path = REPO_ROOT / "bot" / "redis_env.py"

    env_spec = spec_from_file_location("redis_env_local", redis_env_path)
    if env_spec is None or env_spec.loader is None:
        raise RuntimeError(f"Unable to load module spec: {redis_env_path}")

    redis_env_mod = module_from_spec(env_spec)
    env_spec.loader.exec_module(redis_env_mod)
    get_all_redis_urls = redis_env_mod.get_all_redis_urls


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
    return parser.parse_args()


def _tls_auto_insecure(url: str) -> bool:
    _ = url
    return False


def _resp(parts: list[str]) -> bytes:
    body = [f"*{len(parts)}\r\n".encode("utf-8")]
    for part in parts:
        encoded = part.encode("utf-8")
        body.append(f"${len(encoded)}\r\n".encode("utf-8"))
        body.append(encoded + b"\r\n")
    return b"".join(body)


def _read_line(sock_obj: socket.socket) -> bytes:
    buf = bytearray()
    while True:
        chunk = sock_obj.recv(1)
        if not chunk:
            raise RuntimeError("Redis socket closed while reading response")
        buf.extend(chunk)
        if len(buf) >= 2 and buf[-2:] == b"\r\n":
            return bytes(buf[:-2])


def _read_resp(sock_obj: socket.socket):
    prefix = sock_obj.recv(1)
    if not prefix:
        raise RuntimeError("Empty Redis response")

    if prefix == b"+":
        return _read_line(sock_obj).decode("utf-8", errors="replace")
    if prefix == b"-":
        msg = _read_line(sock_obj).decode("utf-8", errors="replace")
        raise RuntimeError(f"Redis error reply: {msg}")
    if prefix == b":":
        return int(_read_line(sock_obj))
    if prefix == b"$":
        size = int(_read_line(sock_obj))
        if size == -1:
            return None
        payload = b""
        while len(payload) < size + 2:
            payload += sock_obj.recv(size + 2 - len(payload))
        return payload[:-2].decode("utf-8", errors="replace")
    if prefix == b"*":
        count = int(_read_line(sock_obj))
        return [_read_resp(sock_obj) for _ in range(max(0, count))]
    raise RuntimeError(f"Unknown Redis RESP prefix: {prefix!r}")


def _ping_once(redis_url: str, timeout_s: float = 5.0) -> str:
    parsed = urlparse(redis_url)
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname
    port = parsed.port
    if not host or port is None:
        raise RuntimeError("Invalid Redis URL (missing host/port)")

    raw_sock = socket.create_connection((host, int(port)), timeout=timeout_s)
    sock_obj: socket.socket = raw_sock
    try:
        if scheme == "rediss":
            if _tls_auto_insecure(redis_url):
                context = ssl._create_unverified_context()
            else:
                context = ssl.create_default_context()
            sock_obj = context.wrap_socket(raw_sock, server_hostname=host)

        if parsed.password:
            user = parsed.username or "default"
            sock_obj.sendall(_resp(["AUTH", user, parsed.password]))
            _read_resp(sock_obj)

        db_raw = (parsed.path or "").lstrip("/")
        db = db_raw if db_raw.isdigit() else "0"
        if db != "0":
            sock_obj.sendall(_resp(["SELECT", db]))
            _read_resp(sock_obj)

        sock_obj.sendall(_resp(["PING"]))
        pong = _read_resp(sock_obj)
        return str(pong)
    finally:
        try:
            sock_obj.close()
        except Exception:
            pass
        if sock_obj is not raw_sock:
            try:
                raw_sock.close()
            except Exception:
                pass


def _is_tlsish_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "ssl" in msg
        or "tls" in msg
        or "handshake" in msg
        or "wrong version" in msg
        or "record layer" in msg
        or "certificate" in msg
        or "timed out" in msg
        or "timeout" in msg
    )


def _prioritized_alt_urls(primary_url: str) -> list[str]:
    configured_urls = [url for _, url in get_all_redis_urls() if url]
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in configured_urls:
        raw = candidate.strip()
        if not raw or raw == primary_url or raw in seen:
            continue
        seen.add(raw)
        unique.append(raw)

    def _priority(url: str) -> tuple[int, str]:
        host = (urlparse(url).hostname or "").lower()
        if host.endswith(".railway.internal"):
            return (0, host)
        if host.endswith(".proxy.rlwy.net") or host.endswith(".up.railway.app"):
            return (3, host)
        if ".rlwy.net" in host:
            return (2, host)
        return (1, host)

    return sorted(unique, key=_priority)


def _build_candidates(primary_url: str) -> list[tuple[str, bool]]:
    primary = primary_url.strip()
    host = (urlparse(primary).hostname or "").lower()
    is_proxy = host.endswith(".proxy.rlwy.net") or host.endswith(".up.railway.app")
    if is_proxy and primary.startswith("redis://"):
        primary = primary.replace("redis://", "rediss://", 1)

    candidates: list[tuple[str, bool]] = [(primary, False)]

    for alt in _prioritized_alt_urls(primary):
        candidates.append((alt, False))
    return candidates


def main() -> int:
    args = parse_args()

    primary_url = (args.redis_url or os.getenv("NIJA_REDIS_URL", "")).strip()
    if not primary_url:
        all_urls = get_all_redis_urls()
        primary_url = all_urls[0][1] if all_urls else ""

    if not primary_url:
        print("ERROR: No Redis URL configured.")
        print(
            "Checked URL sources: NIJA_REDIS_URL, REDIS_PRIVATE_URL, REDIS_PUBLIC_URL, "
            "REDIS_URL (legacy), REDIS_TLS_URL (legacy)"
        )
        return 2

    print(f"Primary Redis candidate: {_redact(primary_url)}")
    _print_candidate_matrix(primary_url)

    candidates = _build_candidates(primary_url)
    print(f"Runtime candidates to try: {len(candidates)}")

    last_error: Exception | None = None
    try:
        selected_url = ""
        pong = ""
        retries = max(1, int(args.retries))
        delay_s = max(0.0, float(args.delay))

        for idx, (candidate_url, tlsish_only) in enumerate(candidates):
            print(f"probe> trying candidate {idx + 1}/{len(candidates)}: {_redact(candidate_url)}")
            for attempt in range(1, retries + 1):
                try:
                    pong = _ping_once(candidate_url)
                    selected_url = candidate_url
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < retries:
                        time.sleep(delay_s)
                        continue

            if selected_url:
                break

            if tlsish_only and last_error is not None and not _is_tlsish_error(last_error):
                print("probe> scheme fallback failed with non-TLS error; continuing with remaining endpoints")
            elif tlsish_only:
                print("probe> TLS/scheme mismatch suspected; moving to next candidate")
            else:
                print("probe> candidate failed; moving to next configured endpoint")

        if not selected_url:
            raise RuntimeError(str(last_error) if last_error else "No candidate succeeded")

        selected_host = (urlparse(selected_url).hostname or "").lower()
        selected_scheme = (urlparse(selected_url).scheme or "").lower()
        is_proxy = selected_host.endswith(".proxy.rlwy.net") or selected_host.endswith(".up.railway.app")

        print("RESULT: Redis connectivity OK")
        print(f"Selected endpoint: {_redact(selected_url)}")
        print(f"Selected host class: {'railway-proxy' if is_proxy else 'internal-or-native'}")
        print(f"Selected TLS scheme: {selected_scheme}")
        print(f"Ping response: {pong}")

        if is_proxy and selected_scheme == "rediss":
            print("CONCLUSION: Railway proxy TLS is working on the selected proxy port.")
        elif is_proxy and selected_scheme != "rediss":
            print("CONCLUSION: Proxy endpoint selected but TLS is not enabled; fix endpoint scheme to rediss://.")
        else:
            print("CONCLUSION: Proxy TLS path was not selected; using internal/native fallback endpoint.")

        return 0
    except Exception as exc:
        print(f"RESULT: Redis connectivity FAILED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
