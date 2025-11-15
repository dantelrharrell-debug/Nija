# decode_jwt_inspect.py
import jwt, json
token = "<PASTE_JWT_HERE>"   # only paste the token *preview* or the whole token if you are comfortable (don't paste private key)
header = jwt.get_unverified_header(token)
payload = jwt.decode(token, options={"verify_signature": False})
print("Header:", json.dumps(header, indent=2))
print("Payload:", json.dumps(payload, indent=2))
