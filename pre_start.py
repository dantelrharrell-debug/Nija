import sys
from nija_client.check_funded import check_funded_accounts

def main():
    print("[INFO] Running pre-start funded accounts check...")
    funded = check_funded_accounts()
    if not funded:
        print("[ERROR] No funded accounts found. Exiting container.")
        sys.exit(1)
    print("[INFO] Funded accounts check passed.")

if __name__ == "__main__":
    main()
