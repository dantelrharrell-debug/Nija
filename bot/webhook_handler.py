import json
from flask import request

class WebhookHandler:
    def __init__(self, callback):
        self.callback = callback

    def handle(self):
        try:
            data = request.json
            if not data:
                return {"status": "error", "message": "No JSON payload"}, 400

            # Pass TradingView alert to your bot callback
            self.callback(data)

            return {"status": "success"}, 200

        except Exception as e:
            return {"status": "error", "message": str(e)}, 500
