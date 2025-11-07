# startup_env.py
import os
import logging
import stat

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("startup_env")

# Load .env if it exists (for local development)
if os.path.exists(".env"):
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
        log.info(".env loaded for local dev")
    except ImportError:
        log.warning("python-dotenv not installed, skipping .env load")

# Write PEM content to a temporary file (if provided)
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if pem_content:
    pem_path = "/tmp/coinbase.pem"
    with open(pem_path, "w") as f:
        f.write(pem_content.replace("\\n", "\n"))
    os.chmod(pem_path, stat.S_IRUSR)  # read-only by owner
    os.environ["COINBASE_PEM_PATH"] = pem_path
    log.info(f"PEM file written to {pem_path}")
else:
    log.warning("COINBASE_PEM_CONTENT not set; make sure you have API keys")
