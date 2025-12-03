# test_pem_format.py
import os, logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pem_test")

PEM = os.getenv("COINBASE_PEM_CONTENT")
if PEM is None:
    logger.error("COINBASE_PEM_CONTENT is not set in environment")
    raise SystemExit(1)

s = PEM.strip().replace("\\n", "\n")
lines = s.splitlines()

logger.info("first line repr: %r", lines[0] if lines else "")
logger.info("last line repr: %r", lines[-1] if lines else "")
logger.info("total lines: %d", len(lines))
logger.info("total chars: %d", len(s))
# show the first 200 bytes and last 200 bytes (repr)
logger.info("start (repr first 200 chars): %r", s[:200])
logger.info("end (repr last 200 chars): %r", s[-200:])

# write to /tmp/test_coinbase.pem for manual inspection
path = "/tmp/test_coinbase.pem"
with open(path, "w") as f:
    f.write(s)
logger.info("Wrote test pem to %s", path)
