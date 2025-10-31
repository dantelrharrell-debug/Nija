def _sanitize_and_normalize_pem(raw_pem: str, from_b64: bool=False) -> str:
    """
    Returns a well-formed PEM string.
    Handles:
    - base64-encoded full PEM (from_b64=True)
    - multi-line PEM
    - escaped \n sequences
    """
    import re
    import base64
    import binascii

    pem = raw_pem.strip()

    if from_b64:
        try:
            # Decode base64 to bytes
            pem_bytes = base64.b64decode(pem + "=" * (-len(pem) % 4))
            try:
                # Try decoding as UTF-8
                pem = pem_bytes.decode("utf-8")
            except UnicodeDecodeError:
                # If binary, re-wrap as PEM
                body = base64.b64encode(pem_bytes).decode("ascii")
                pem = "-----BEGIN EC PRIVATE KEY-----\n"
                pem += "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
                pem += "\n-----END EC PRIVATE KEY-----\n"
        except binascii.Error as e:
            raise ValueError(f"Failed to decode base64 PEM: {e}")

    # Convert literal \n to real newlines
    if "\\n" in pem:
        pem = pem.replace("\\n", "\n")

    # Strip quotes if present
    if (pem.startswith('"') and pem.endswith('"')) or (pem.startswith("'") and pem.endswith("'")):
        pem = pem[1:-1].strip()

    # Ensure proper BEGIN/END if missing
    if "BEGIN" not in pem or "END" not in pem:
        body = "".join(pem.split())
        pem = "-----BEGIN EC PRIVATE KEY-----\n"
        pem += "\n".join([body[i:i+64] for i in range(0, len(body), 64)])
        pem += "\n-----END EC PRIVATE KEY-----\n"

    return pem
