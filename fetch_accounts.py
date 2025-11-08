import os
from nija_coinbase_jwt_client import CoinbaseJWTClient

def fix_pem(pem_env_var: str) -> str:
    """Fix PEM formatting for JWT secret."""
    pem = os.getenv(pem_env_var, "")
    return pem.replace("\\n", "\n")

def main():
    # Fix the PEM key
    os.environ["COINBASE_API_SECRET"] = fix_pem("COINBASE_API_SECRET")
    
    # Initialize the JWT client
    try:
        client = CoinbaseJWTClient()
        accounts = client.get_accounts()
        print("✅ Accounts fetched successfully:")
        for acc in accounts:
            print(acc)
    except Exception as e:
        print(f"❌ Failed to fetch accounts: {e}")

if __name__ == "__main__":
    main()
