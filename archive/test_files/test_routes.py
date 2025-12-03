import requests

# Replace with your container IP / localhost if mapped
url_root = "http://127.0.0.1:5000/"
url_health = "http://127.0.0.1:5000/health"

try:
    r1 = requests.get(url_root)
    print(f"/ response: {r1.status_code} | {r1.text}")
except Exception as e:
    print(f"Error accessing / : {e}")

try:
    r2 = requests.get(url_health)
    print(f"/health response: {r2.status_code} | {r2.json()}")
except Exception as e:
    print(f"Error accessing /health : {e}")
