import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

pem_content = os.environ.get("COINBASE_PEM_CONTENT")
pem_path = "/app/coinbase.pem"

# write PEM file
with open(pem_path, "w", newline="\n") as f:
    f.write(pem_content.replace("\\n", "\n"))

# try loading
with open(pem_path, "rb") as f:
    key_data = f.read()

key = serialization.load_pem_private_key(key_data, password=None, backend=default_backend())
print("✅ PEM loaded successfully. Key type:", type(key))
