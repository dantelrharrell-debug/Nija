# test_pem_format.py
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_pem_test")

# 1️⃣ Read PEM from environment variable
PEM_STRING = os.getenv("COINBASE_PEM_CONTENT")
if not PEM_STRING:
    logger.error("COINBASE_PEM_CONTENT is not set!")
    raise SystemExit(1)

# 2️⃣ Replace literal \n with real newlines
formatted_pem = PEM_STRING.replace("\\n", "\n")

# 3️⃣ Optional: remove extra spaces at start/end
formatted_pem = formatted_pem.strip()

# 4️⃣ Print first/last lines and length for sanity check
lines = formatted_pem.splitlines()
logger.info(f"PEM starts with: {lines[0]}")
logger.info(f"PEM ends with: {lines[-1]}")
logger.info(f"PEM total lines: {len(lines)}")
logger.info(f"PEM total chars: {len(formatted_pem)}")

# 5️⃣ Optional: write to temp file to test loading
test_path = "/tmp/test_coinbase.pem"
with open(test_path, "w") as f:
    f.write(formatted_pem)
logger.info(f"PEM written to {test_path} for verification ✅")

# You can now manually inspect /tmp/test_coinbase.pem in the container
