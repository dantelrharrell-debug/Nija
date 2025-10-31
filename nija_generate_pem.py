# nija_generate_pem.py
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

private_key = ec.generate_private_key(ec.SECP256R1())  # prime256v1 / P-256

pem_bytes = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,  # "EC PRIVATE KEY"
    encryption_algorithm=serialization.NoEncryption()
)

print("==== BEGIN GENERATED PEM (copy everything between the markers) ====")
print(pem_bytes.decode("utf-8"))
print("==== END GENERATED PEM ====")
