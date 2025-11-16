from app.nija_client import CoinbaseClient
from loguru import logger

if __name__ == "__main__":
    api_key = "d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"
    kid = "9e33d60c-c9d7-4318-a2d5-24e1e53d2206"
    org_id = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
    pem = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIKrWQ2OeX7kqTob0aXR6A238b698ePPLutcEP1qq4gfLoAoGCCqGSM49
AwEHoUQDQgAEuQAqrVE522Hz...
-----END EC PRIVATE KEY-----"""

    client = CoinbaseClient(api_key=api_key, org_id=org_id, pem=pem, kid=kid)
    status, resp = client.request_auto("GET", "/v2/accounts")
    logger.info(f"API test status: {status}")
    logger.info(f"API response: {resp}")
