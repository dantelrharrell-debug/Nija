# === Auto-generate JWT from PEM env or file path ===
import os, time
try:
    import jwt as pyjwt
    PYJWT_AVAILABLE = True
except ImportError:
    PYJWT_AVAILABLE = False

pem_from_env = os.getenv("COINBASE_PEM_CONTENT", "") or None
if not getattr(self, "jwt", None) and (getattr(self, "private_key_path", None) or pem_from_env) and getattr(self, "org_id", None):
    if PYJWT_AVAILABLE:
        try:
            if pem_from_env:
                pem_bytes = pem_from_env.encode("utf-8")
                now = int(time.time())
                payload = {
                    "iss": self.org_id,
                    "sub": self.org_id,
                    "iat": now,
                    "exp": now + 300,  # 5 minutes TTL
                    "aud": "coinbase",
                }
                token = pyjwt.encode(payload, pem_bytes, algorithm="ES256")
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                print("✅ Auto-generated ephemeral JWT from COINBASE_PEM_CONTENT (env).")
            elif getattr(self, "private_key_path", None):
                # fallback: existing PEM path method
                token = self._generate_jwt_from_pem()
                if token:
                    self.jwt = token
                    print("✅ Auto-generated ephemeral JWT from PEM path.")
        except Exception as e:
            print(f"⚠️ JWT auto-generation failed: {e}")
    else:
        print("⚠️ PyJWT not installed: cannot auto-generate JWT from PEM.")
