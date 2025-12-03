# debug_nija_write_pem.py  (temporary - safe)
import os, logging, stat
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("debug_pem")

val = os.getenv("COINBASE_PEM_CONTENT")
if val is None:
    log.error("COINBASE_PEM_CONTENT not set")
    raise SystemExit(1)

s = val.strip()
s_singleline_converted = s.replace("\\n", "\n")
lines = s_singleline_converted.splitlines()

log.info("PEM (first line repr): %r", lines[0] if lines else "")
log.info("PEM (last  line repr): %r", lines[-1] if lines else "")
log.info("PEM total lines: %d", len(lines))
log.info("PEM total chars: %d", len(s_singleline_converted))
log.info("PEM start repr (200 chars): %r", s_singleline_converted[:200])
log.info("PEM end   repr (200 chars): %r", s_singleline_converted[-200:])

path = "/tmp/debug_coinbase.pem"
with open(path, "w", newline="\n") as f:
    f.write(s_singleline_converted)
os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
log.info("Wrote debug PEM to %s (permissions set to 600)", path)

# STOP here so client won't attempt to use a bad key
raise SystemExit(0)
