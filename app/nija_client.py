# inside app/nija_client.py — replace or augment PEM normalization in __init__

import base64

# ... inside __init__ after reading raw envs:
self.pem_content_raw = os.getenv("COINBASE_JWT_PEM")
pem_b64 = os.getenv("COINBASE_JWT_PEM_B64")  # new optional env

self.pem_content = None

def _clean_candidate(s: str) -> str:
    if not s:
        return s
    s = s.strip()
    # remove surrounding quotes if someone pasted them
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    # convert literal \n sequences into real newlines (common UI paste)
    if "\\n" in s and "\n" not in s:
        s = s.replace("\\n", "\n")
    return s

# 1) if we have a direct PEM env, clean and use it
if self.pem_content_raw:
    cleaned = _clean_candidate(self.pem_content_raw)
    # quick sanity check for PEM framing
    if cleaned.startswith("-----BEGIN") and "PRIVATE KEY-----" in cleaned:
        self.pem_content = cleaned
    else:
        # not obviously a valid PEM — keep cleaned but will try further below
        self.pem_content = cleaned

# 2) fallback: if not PEM but there is a base64 env, decode it
if not self.pem_content and pem_b64:
    cleaned_b64 = _clean_candidate(pem_b64)
    try:
        decoded = base64.b64decode(cleaned_b64)
        # decoded is bytes; convert to str
        decoded_str = decoded.decode("utf-8", errors="ignore")
        if decoded_str.startswith("-----BEGIN") and "PRIVATE KEY-----" in decoded_str:
            self.pem_content = decoded_str
            logger.debug("Loaded PEM from COINBASE_JWT_PEM_B64 (decoded).")
        else:
            logger.warning("COINBASE_JWT_PEM_B64 decoded but does not contain PEM framing.")
    except Exception as e:
        logger.exception("Failed to decode COINBASE_JWT_PEM_B64: %s", e)

# 3) last-ditch: if pem_content contains literal / escaped \\n, normalize
if self.pem_content and "\\n" in self.pem_content and "\n" not in self.pem_content:
    self.pem_content = self.pem_content.replace("\\n", "\n")
    logger.debug("Normalized PEM by replacing literal \\n with newlines.")

# 4) final sanity: ensure PEM contains BEGIN/END
if self.pem_content:
    if not (self.pem_content.startswith("-----BEGIN") and "END" in self.pem_content):
        logger.warning("PEM present but does not look well-formed (missing BEGIN/END).")
else:
    logger.debug("No PEM content available from COINBASE_JWT_PEM or COINBASE_JWT_PEM_B64.")
