import requests

url = "https://nija-trading-bot-v9xl.onrender.com/webhook"
payload = {
    "secret": "nija_webhook_2025",
    "action": "buy",
    "symbol": "BTC-USD",
    "size": 10.0,
    "message": "Test buy from Copilot"
}
headers = {"Content-Type": "application/json"}

response = requests.post(url, json=payload, headers=headers)
print(response.status_code)
print(response.json())
