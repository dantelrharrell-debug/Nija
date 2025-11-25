# === Base Image ===
FROM python:3.11-slim

# === Set working directory ===
WORKDIR /app

# === Install system dependencies ===
RUN apt-get update && apt-get install -y git ca-certificates --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# === Copy requirements and code ===
COPY requirements.txt .
COPY . .

# === Make start script executable ===
RUN chmod +x ./start_all.sh || true

# === Upgrade pip/setuptools/wheel and install Python deps ===
RUN python -m pip install --upgrade pip setuptools wheel

# === Install private repo securely ===
RUN if [ -n "${GH_TOKEN}" ]; then \
        echo "Installing private repo coinbase-advanced using GH_TOKEN"; \
        python -m pip install "git+https://${GH_TOKEN}@github.com/dantelrharrell-debug/coinbase-advanced.git@main"; \
        grep -v -E "coinbase-advanced" requirements.txt > /tmp/reqs_for_pip.txt || true; \
        python -m pip install -r /tmp/reqs_for_pip.txt; \
        shred -u /tmp/reqs_for_pip.txt || rm -f /tmp/reqs_for_pip.txt; \
        unset GH_TOKEN; \
    else \
        echo "Error: GH_TOKEN missing. Cannot install private repo. Exiting build."; \
        exit 1; \
    fi

# === Expose Flask port ===
EXPOSE 5000

# === Start the bot ===
CMD ["./start_all.sh"]
