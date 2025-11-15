# check_pem.py
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

with open("coinbase.pem","rb") as f: data = f.read()
print("PEM length bytes:", len(data))
try:
    key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
    print("PEM loads OK.")
except Exception as e:
    print("PEM load failed:", e)
