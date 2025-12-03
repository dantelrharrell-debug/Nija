# fix_check_pem.py
import os
import logging
import re
import base64
from html import unescape

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def strip_export_lines(s: str) -> str:
    # remove lines like: export COINBASE_PEM_CONTENT='...'
    return "\n".join([re.sub(r"^\s*export\s+\w+=\s*", "", line) for line in s.splitlines()])

def remove_html_wrappers(s: str) -> str:
    # remove common wrappers and tags (<pre>, <code>, HTML-encoded <br> etc)
    s = unescape(s)  # convert &lt; &gt; etc
    s = re.sub(r"</?(pre|code|textarea)[^>]*>", "", s, flags=re.IGNORECASE)
    # remove leading/trailing <...> lines if entire block came inside an HTML tag
    s = re.sub(r"^\s*<[^>\n]+>\s*", "", s)
    s = re.sub(r"\s*<[^>\n]+>\s*$", "", s)
    return s

def unwrap_quotes(s: str) -> str:
    # remove wrapping single/double quotes around entire value
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s

def convert_escaped_newlines(s: str) -> str:
    # convert literal \n sequences into real newlines
    if r"\n" in s:
        s = s.replace("\\n", "\n")
    return s

def looks_like_base64(s: str) -> bool:
    # Quick heuristic: no spaces, only base64 chars and '=' padding present, length reasonable
    candidate = "".join(s.split())
    if len(candidate) < 100:
        return False
    return re.fullmatch(r"[A-Za-z0-9+/=\s]+", s) is not None and ("-----" not in s)

def try_base64_decode(s: str) -> str:
    try:
        candidate = "".join(s.split())
        decoded = base64.b64decode(candidate)
        # decoded must be text with BEGIN/END
        txt = decoded.decode("utf-8", errors="ignore")
        if "BEGIN" in txt:
            logging.info("Detected base64-encoded PEM; decoded successfully.")
            return txt
    except Exception:
        pass
    return s

def normalize_pem(raw: str) -> str:
    if raw is None:
        return ""
    s = raw
    s = strip_export_lines(s)
    s = unwrap_quotes(s)
    s = remove_html_wrappers(s)
    s = convert_escaped_newlines(s)
    s = s.strip()

    # If it looks base64-ish, try decoding
    if looks_like_base64(s):
        s2 = try_base64_decode(s)
        if "BEGIN" in s2:
            s = s2

    # final cleanup: remove weird leading characters like '<' if still present
    # but we don't silently fix those — show a warning if present
    return s

def basic_checks(pem: str) -> bool:
    if not pem:
        logging.error("COINBASE_PEM_CONTENT empty after normalization.")
        return False
    if "<" in pem[:20]:
        logging.error("PEM still begins with '<' — likely HTML wrapper remained. Paste raw PEM.")
        return False
    if "-----BEGIN" not in pem or "-----END" not in pem:
        logging.error("PEM missing header or footer (-----BEGIN... / -----END...).")
        return False
    # ensure header is first non-empty line
    lines = [l for l in pem.splitlines() if l.strip() != ""]
    if not lines:
        logging.error("PEM blank after stripping empty lines.")
        return False
    if not lines[0].startswith("-----BEGIN"):
        logging.error("First non-empty line is not PEM header.")
        return False
    if not lines[-1].startswith("-----END"):
        logging.error("Last non-empty line is not PEM footer.")
        return False
    # basic length check
    body_len = sum(len(l.strip()) for l in lines[1:-1])
    if body_len < 50:
        logging.error("PEM body looks too short to be a valid EC private key.")
        return False
    return True

def write_debug_pem(pem: str, path="/tmp/coinbase_pem_debug.pem"):
    try:
        with open(path, "w") as f:
            f.write(pem)
        logging.info(f"Saved normalized PEM to {path}")
    except Exception as e:
        logging.error(f"Failed to write {path}: {e}")

def main():
    raw = os.getenv("COINBASE_PEM_CONTENT")
    api_key = os.getenv("COINBASE_API_KEY_ID")
    org_id = os.getenv("COINBASE_ORG_ID")

    if api_key and org_id:
        logging.info("COINBASE_ORG_ID and COINBASE_API_KEY_ID present.")
    else:
        logging.warning("COINBASE_ORG_ID or COINBASE_API_KEY_ID missing or empty.")

    pem = normalize_pem(raw)

    # show short preview for debugging (first 2 lines)
    preview = "\n".join(pem.splitlines()[:2])
    logging.info(f"PEM preview (first lines): {repr(preview[:200])}")

    if basic_checks(pem):
        write_debug_pem(pem)
        logging.info("PEM normalization and basic checks passed.")
        logging.info("Now check Coinbase key <-> org match and IP whitelist.")
        exit(0)
    else:
        logging.error("PEM verification failed. See messages above for which check failed.")
        # also dump a small diagnostic file if we can
        try:
            with open("/tmp/coinbase_pem_diag.txt", "w") as f:
                f.write("RAW_ENV_PREVIEW:\n")
                f.write((raw or "")[:1000])
        except Exception:
            pass
        exit(2)

if __name__ == "__main__":
    main()
