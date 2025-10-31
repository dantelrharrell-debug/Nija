import re
import base64
import logging

logger = logging.getLogger("nija_coinbase_jwt")

def _sanitize_and_normalize_pem(raw_pem: str, from_b64: bool=False):
    """
    Normalize PEM for jwt.encode:
      - Accepts full PEM text, single-line with '\n', or base64 body
      - If from_b64=True, decodes base64 (can be binary DER)
      - Returns either UTF-8 string (PEM) or bytes (DER) suitable for jwt.encode
    """
    if not raw_pem:
        raise ValueError("No PEM provided in environment")

    pem = raw_pem.strip()

    if from_b64:
        # remove whitespace/newlines
        s = re.sub(r"\s+", "", pem)
        padded = s + ("=" * (-len(s) % 4))
        try:
            pem_bytes = base64.b64decode(padded)
        except Exception as e:
            logger.error("[NIJA-JWT] Failed to decode COINBASE_PEM_KEY_B64: %s", e)
            raise
        # Try decode UTF-8 for PEM header normalization, fallback to bytes
        try:
            pem_str = pem_bytes.decode("utf-8")
            pem = pem_str
        except UnicodeDecodeError:
            logger.warning("[NIJA-JWT] PEM is binary; using raw bytes")
            return pem_bytes  # keep as bytes for jwt.encode

    # Convert literal '\n' sequences to real newlines
    if "\\n" in pem and "BEGIN" in pem and "END" in pem:
        pem = pem.replace("\\n", "\n")

    # Strip surrounding quotes if present
    if (pem.startswith('"') and pem.endswith('"')) or (pem.startswith("'") and pem.endswith("'")):
        pem = pem[1:-1].strip()

    # If PEM already has header/trailer, normalize spacing
    if "-----BEGIN" in pem and "-----END" in pem:
        pem = pem.strip()
        if not pem.endswith("\n"):
            pem += "\n"
        return pem

    # If it looks like base64 body, wrap it with header/trailer
    if re.fullmatch(r"[A-Za-z0-9+/=]+", pem) and len(pem) > 40:
        logger.info("[NIJA-JWT] Detected base64 PEM body; wrapping with BEGIN/END headers")
        body = "".join(pem.split())
        wrapped = "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
        pem_full = "-----BEGIN EC PRIVATE KEY-----\n" + wrapped + "\n-----END EC PRIVATE KEY-----\n"
        return pem_full

    # fallback: return as-is
    return pem
