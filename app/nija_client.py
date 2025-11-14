# debug_jwt_info.py (paste into repo and run in container)
import os, time, base64, json
from loguru import logger
import jwt  # pyjwt

logger.remove()
logger.add(lambda m: print(m, end=""))

API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")

# fix escaped newlines
if "\\n" in PEM_RAW:
    PEM = PEM_RAW.replace("\\n", "\n")
else:
    PEM = PEM_RAW

logger.info(f"Container local time (epoch): {int(time.time())}")
logger.info(f"Container local time (iso): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC")

# build a short JWT header+payload (do not print signature)
try:
    payload = {"sub": API_KEY or "missing", "iat": int(time.time()), "exp": int(time.time()) + 300}
    token = jwt.encode(payload, PEM, algorithm="ES256", headers={"kid": API_KEY})
    logger.info("Generated token length: %d" % len(token))
    # decode header/payload only (safe)
    header_b64, payload_b64, _ = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "==").decode())
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode())
    logger.info("JWT header preview (safe): %s" % json.dumps(header))
    logger.info("JWT payload preview (safe): %s" % json.dumps(payload))
except Exception as e:
    logger.error(f"JWT creation/inspect error: {type(e).__name__}: {e}")
