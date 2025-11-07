from flask import Flask
from nija_client import CoinbaseClient  # keep this at the top

app = Flask(__name__)

@app.route("/check_accounts_readable", methods=["GET"])
def check_accounts_readable():
    """
    Returns a simple HTML page with all Coinbase account balances.
    Safe: READ-ONLY, no trades executed.
    """
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()
        
        html_output = "<h2>Your Coinbase Balances</h2><ul>"
        for acct in accounts:
            html_output += f"<li>{acct['currency']}: {acct['balance']}</li>"
        html_output += "</ul>"
        
        return html_output
    except Exception as e:
        return f"<p>Error fetching accounts: {str(e)}</p>", 500

# Make sure the app.run() is at the bottom
if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
