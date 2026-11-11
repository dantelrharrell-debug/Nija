"""In-memory limits for a single offline synthetic test run."""
class Budget:
    def __init__(self, max_requests=100):
        self.max_requests = max_requests
        self.used = 0

    def consume(self):
        if self.used >= self.max_requests:
            raise RuntimeError("Pilot request limit reached")
        self.used += 1
