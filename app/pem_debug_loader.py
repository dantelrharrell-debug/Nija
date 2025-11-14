# app/pem_debug_loader.py
import os
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import base64
import binascii

logger.remove()
logger.add(lambda m: print(m, end=""))

logger.info("=== PEM DEBUG LOADER START ===")

# Try prioritized sources:
# 1) COINBASE_PEM_B64  (recommended: paste base64 of PEM into env, single-line)
# 2) COINBASE_PEM_CONTENT (accepts real multiline or literal "\n" sequences)
pem_b64_env = os.environ.get("COINBASE_PEM_B64", "").strip()
pem_content_env = os.environ.get("COINBASE_PEM_CONTENT", "")

pem = None

if pem_b64_env:
    logger.info("Found COINBASE_PEM_B64 (base64). Decoding...")
    try:
        pem = base64.b64decode(pem_b64_env).decode("utf-8")
        logger.info(f"Decoded PEM length: {len(pem)}")
    except Exception as e:
        logger.error(f"Failed to base64-decode COINBASE_PEM_B64: {e}")
        # Try to show first 200 chars of base64 input (safe)
        logger.info("Preview (first 200 chars) of COINBASE_PEM_B64:")
        logger.info(pem_b64_env[:200])
elif pem_content_env:
    logger.info("Found COINBASE_PEM_CONTENT. Normalizing newlines...")
    if "\\n" in pem_content_env and "\n" not in pem_content_env:
        # convert literal backslash-n sequences
        pem = pem_content_env.replace("\\n", "\n")
        logger.info("Replaced literal \\n sequences -> newline characters.")
    else:
        pem = pem_content_env
    logger.info(f"Normalized PEM length: {len(pem)}")
else:
    logger.error("No COINBASE_PEM_B64 or COINBASE_PEM_CONTENT found in env.")
    pem = ""

# quick header/footer checks
if pem:
    lines = [l for l in pem.splitlines() if l.strip() != ""]
    if not lines:
        logger.error("PEM is empty after splitting lines.")
    else:
        logger.info(f"First line preview: {repr(lines[0])}")
        logger.info(f"Last line preview:  {repr(lines[-1])}")

    # Extract base64 body between BEGIN and END
    try:
        start = pem.index("-----BEGIN")
        end = pem.index("-----END")
        header = pem[: pem.index("\n")].strip() if "\n" in pem else pem[:80]
        logger.info(f"Header line: {header}")
        # body lines between first blank after header and before footer
        body = []
        in_body = False
        for ln in pem.splitlines():
            if ln.startswith("-----BEGIN"):
                in_body = True
                continue
            if ln.startswith("-----END"):
                break
            if in_body:
                body.append(ln.strip())
        body_str = "\n".join(body)
        logger.info(f"Base64 body length (chars): {len(body_str)}")
    except ValueError:
        logger.warning("PEM header/footer not found with standard markers. Will analyze whole content.")
        body_str = "".join([c for c in pem if c.strip()])  # non-whitespace

    # Validate characters in the base64 body (PEM body should only contain A-Za-z0-9+/=)
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r ")
    bad = []
    for i, ch in enumerate(body_str):
        if ch not in allowed:
            bad.append((i, ch))
            if len(bad) >= 50:
                break

    if bad:
        logger.error("❌ Invalid characters found in PEM base64 body (index, repr):")
        for idx, ch in bad:
            logger.error(f"  index {idx}: {repr(ch)}  (ord={ord(ch)})")
        logger.error("Common issues: literal '\\n' sequences not converted, accidental quotes, extra commas, or truncated paste.")
    else:
        logger.info("✅ No invalid characters detected in PEM base64 body (basic check).")

    # If body seems very short, warn (EC keys typically have body length > 200)
    if len(body_str) < 200:
        logger.warning(f"PEM base64 body is short ({len(body_str)} chars). The key may be truncated or missing.")

    # Try to load the key with cryptography to show exact exception
    try:
        priv = serialization.load_pem_private_key(pem.encode("utf-8"), password=None, backend=default_backend())
        logger.info("✅ Private key parsed successfully.")
        # print a short public key preview
        pub = priv.public_key().public_bytes(encoding=serialization.Encoding.PEM,
                                            format=serialization.PublicFormat.SubjectPublicKeyInfo)
        logger.info("Public key preview (first 3 lines):")
        for i, line in enumerate(pub.decode().splitlines()[:3]):
            logger.info(f"  {line}")
    except Exception as e:
        logger.error("❌ cryptography failed to load key:")
        logger.error(repr(e))
        # try to show a hexdump of the first 200 bytes to inspect invalid bytes
        try:
            raw = pem.encode("utf-8")
            preview = raw[:200]
            hexd = " ".join(f"{b:02x}" for b in preview)
            logger.info("Hex preview (first 200 bytes):")
            logger.info(hexd)
        except Exception:
            pass

logger.info("=== PEM DEBUG LOADER END ===")
