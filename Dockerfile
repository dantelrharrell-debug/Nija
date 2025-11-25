FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y git ca-certificates --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN chmod +x ./start_all.sh || true
RUN python -m pip install --upgrade pip setuptools wheel

# Install vendored package if folder exists, then other requirements
RUN if [ -d "./coinbase-advanced" ]; then \
      echo "Installing local vendored coinbase-advanced"; \
      python -m pip install --no-cache-dir ./coinbase-advanced; \
    else \
      echo "Vendored coinbase-advanced not found — proceed"; \
    fi && \
    python -m pip install --no-cache-dir -r requirements.txt

EXPOSE 5000
CMD ["./start_all.sh"]
