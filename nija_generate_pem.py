# nija_generate_pem.py
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

# Generate a new EC private key (P-256 curve)
private_key = ec.generate_private_key(ec.SECP256R1())

# Export PEM in traditional "EC PRIVATE KEY" format
pem_bytes = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,  # EC PRIVATE KEY
    encryption_algorithm=serialization.NoEncryption()
)

pem_str = pem_bytes.decode()
print("==== COPY EVERYTHING BELOW THIS LINE ====")
print(pem_str)
print("==== COPY EVERYTHING ABOVE THIS LINE ====")
