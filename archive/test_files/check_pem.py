# check_pem.py
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

path = "coinbase.pem"   # the file you downloaded
with open(path, "rb") as f:
    data = f.read()
print("PEM byte length:", len(data))
try:
    key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
    print("PEM loads OK.")
except Exception as e:
    print("PEM load failed:", repr(e))
