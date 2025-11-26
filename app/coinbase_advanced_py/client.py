# lightweight local stub used only for development / debugging.
class Client:
    def __init__(self, api_key=None, api_secret=None, api_sub=None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_sub = api_sub

    def get_accounts(self):
        return [{"id": "stub-account", "balance": "0"}]

    def __repr__(self):
        return "<StubCoinbaseClient>"
