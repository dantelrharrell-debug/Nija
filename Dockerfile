# Use Python 3.11 slim
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y git ca-certificates --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker cache optimization)
COPY requirements.txt .

# Upgrade pip, setuptools, wheel
RUN python -m pip install --upgrade pip setuptools wheel

# Install private repo if GH_TOKEN is set
RUN if [ -n "${GH_TOKEN}" ]; then \
        echo "Installing private repo coinbase-advanced using GH_TOKEN"; \
        python -m pip install "git+https://${GH_TOKEN}@github.com/dantelrharrell-debug/coinbase-advanced.git@main"; \
        grep -v -E "coinbase-advanced" requirements.txt > /tmp/reqs_for_pip.txt || true; \
        python -m pip install -r /tmp/reqs_for_pip.txt; \
        shred -u /tmp/reqs_for_pip.txt || rm -f /tmp/reqs_for_pip.txt; \
        unset GH_TOKEN; \
    else \
        echo "Error: GH_TOKEN missing. Cannot install private repo."; \
        exit 1; \
    fi

# Copy the rest of the app
COPY . .

# Ensure start script is executable
RUN chmod +x ./start_all.sh

# Default command
CMD ["./start_all.sh"]
