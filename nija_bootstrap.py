import os

PEM_PATH = "/tmp/coinbase.pem"
pem_content = os.getenv("COINBASE_PEM_CONTENT", "")

if not pem_content:
    raise RuntimeError("[NIJA] COINBASE_PEM_CONTENT not found!")

# Fix literal \n into real newlines
pem_content = pem_content.replace("\\n", "\n")

with open(PEM_PATH, "w") as f:
    f.write(pem_content)

# Set secure permissions
os.chmod(PEM_PATH, 0o600)

# Now init client
from nija_client import init_client
client = init_client(pem_path=PEM_PATH)
