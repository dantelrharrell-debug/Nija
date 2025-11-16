# fix_and_test_pem.py
import os, re, html, sys, time
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# CONFIG: env names your container might use
PEM_PATH = os.getenv("COINBASE_PEM_PATH")          # file path (preferred)
PEM_CONTENT_ENV = os.getenv("COINBASE_PEM_CONTENT") # or raw content with literal \n
OUT_PATH = "/tmp/fixed_coinbase.pem"

def show_snip(s, n=400):
    if not s:
        return "<EMPTY>"
    # replace newlines with \n so we can see them
    display = s[:n].replace("\n", "\\n").replace("\r", "\\r")
    return display + ("..." if len(s) > n else "")

def try_load(pem_text):
    try:
        key = serialization.load_pem_private_key(
            pem_text.encode(), password=None, backend=default_backend()
        )
        return True, None
    except Exception as e:
        return False, str(e)

def clean_common_wrappers(text):
    orig = text
    t = text
    # If it's an HTML page, try to pull the PEM between BEGIN/END
    if "<" in t[:200] and "BEGIN" in t:
        m = re.search(r"(-----BEGIN [^-]+-----.*?-----END [^-]+-----)", t, flags=re.S)
        if m:
            t = m.group(1)
    # Remove HTML tags if accidentally included
    if "<" in t and ">" in t:
        # unescape HTML entities first
        t = html.unescape(t)
        # remove tags naive
        t = re.sub(r"<[^>]+>", "", t)
    # Convert literal \n into real newlines
    if "\\n" in t and "-----BEGIN" in t:
        t = t.replace("\\n", "\n")
    # Strip leading/trailing quotes and whitespace
    t = t.strip().strip('"').strip("'")
    # Remove possible javascript var assignment like: var pem = "-----BEGIN..."
    if "-----BEGIN" in t and not t.startswith("-----BEGIN"):
        idx = t.find("-----BEGIN")
        t = t[idx:]
    # Ensure proper single trailing newline
    if "-----END" in t:
        end_idx = t.find("-----END")
        end_line = t[end_idx:]
        if not end_line.strip().endswith("-----END EC PRIVATE KEY-----"):
            # keep whatever end we have
            pass
    return t

def main():
    print("=== fix_and_test_pem.py ===")
    print("PEM_PATH:", PEM_PATH)
    print("Has PEM_CONTENT env:", bool(PEM_CONTENT_ENV))
    raw = None

    if PEM_CONTENT_ENV:
        raw = PEM_CONTENT_ENV
        print("Loaded PEM from COINBASE_PEM_CONTENT (raw).")
    elif PEM_PATH and os.path.exists(PEM_PATH):
        with open(PEM_PATH, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        print("Loaded PEM from COINBASE_PEM_PATH.")
    else:
        print("No PEM found in env or path. Exiting.")
        sys.exit(2)

    print("\n--- RAW SNIPPET (first 400 chars, newlines shown as \\n) ---")
    print(show_snip(raw, 400))
    print("----------------------------------------------------------------\n")

    # Try loading raw first
    ok, err = try_load(raw.replace("\r", ""))
    if ok:
        print("✅ Raw PEM loads fine (no cleaning necessary).")
        open(OUT_PATH, "w", encoding="utf-8").write(raw)
        print("Saved raw PEM to:", OUT_PATH)
        return

    print("Raw PEM failed to load:", err)
    print("Trying cleaning heuristics...")

    cleaned = clean_common_wrappers(raw)
    print("\n--- CLEANED SNIPPET (first 400 chars) ---")
    print(show_snip(cleaned, 400))
    ok2, err2 = try_load(cleaned)
    if ok2:
        print("✅ Cleaned PEM loaded successfully.")
        open(OUT_PATH, "w", encoding="utf-8").write(cleaned)
        print("Saved cleaned PEM to:", OUT_PATH)
        return

    print("Cleaned PEM still failed:", err2)

    # Extra attempt: remove any non-base64 or non-PEM lines before/after
    m = re.search(r"(-----BEGIN [^-]+-----(?:.|\n)+?-----END [^-]+-----)", cleaned, flags=re.S)
    if m:
        better = m.group(1).strip()
        print("\n--- EXTRACTED SNIPPET (first 400 chars) ---")
        print(show_snip(better, 400))
        ok3, err3 = try_load(better)
        if ok3:
            print("✅ Extracted PEM loaded successfully.")
            open(OUT_PATH, "w", encoding="utf-8").write(better)
            print("Saved extracted PEM to:", OUT_PATH)
            return
        else:
            print("Extracted PEM still failed:", err3)

    print("\n❌ All cleaning attempts failed. Diagnostics below:")
    print("- First raw 400 chars (escaped):")
    print(show_snip(raw, 400))
    print("- Cleaned 400 chars (escaped):")
    print(show_snip(cleaned, 400))
    print("\nActionable suggestions:")
    print("1) If the raw snippet begins with '<' or contains '<html>' -> you pasted an HTML page. Re-download the PEM file directly from Coinbase (do NOT copy from a browser viewer).")
    print("2) If the snippet has JSON or other wrappers, remove them and use only the PEM block between BEGIN/END.")
    print("3) Best fix: on Coinbase Advanced regenerate the API key, download the PEM file, then upload the raw PEM file to your host's secret manager and set COINBASE_PEM_PATH to that secret path.")
    print("\nIf you paste the first ~800 characters that the script printed here I will analyze it and tell you exactly what is wrong.")
    sys.exit(3)

if __name__ == "__main__":
    main()
