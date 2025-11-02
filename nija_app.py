import os

PEM_PATH = "/tmp/coinbase.pem"

# Write PEM content from Render secret to temporary file
pem_content = os.getenv("COINBASE_PEM_CONTENT", "")
if not pem_content:
    raise RuntimeError("[NIJA] COINBASE_PEM_CONTENT not found in environment!")

with open(PEM_PATH, "w") as f:
    f.write(pem_content.replace("\\n", "\n"))

# Make sure file is readable
os.chmod(PEM_PATH, 0o600)

# Now initialize your client using PEM_PATH
from nija_client import init_client
client = init_client(pem_path=PEM_PATH)
