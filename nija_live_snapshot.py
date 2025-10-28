import base64

def decode_pem_b64(api_pem_b64: str) -> bytes:
    # Remove all non-base64 characters (newlines, spaces, etc.)
    sanitized = ''.join(c for c in api_pem_b64 if c.isalnum() or c in '+/=')
    
    # Fix padding
    missing_padding = len(sanitized) % 4
    if missing_padding:
        sanitized += '=' * (4 - missing_padding)
    
    return base64.b64decode(sanitized)

# Then replace:
# f.write(base64.b64decode(API_PEM_B64))
# with:
f.write(decode_pem_b64(API_PEM_B64))
