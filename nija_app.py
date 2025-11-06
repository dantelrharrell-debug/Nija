from flask import Flask, jsonify
from nija_client import get_account_balance, calculate_position_size, place_order

app = Flask(__name__)

@app.route("/")
def home():
    balance = get_account_balance()
    position = calculate_position_size(balance)
    return jsonify({
        "status": "live",
        "balance": balance,
        "position_size": position
    })

@app.route("/buy/<symbol>")
def buy(symbol):
    balance = get_account_balance()
    size = calculate_position_size(balance)
    result = place_order(symbol, "buy", size)
    return jsonify(result)

@app.route("/sell/<symbol>")
def sell(symbol):
    balance = get_account_balance()
    size = calculate_position_size(balance)
    result = place_order(symbol, "sell", size)
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
