# ---------- Builder Stage ----------
FROM python:3.11-slim AS builder

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /src

# Upgrade pip and core Python packaging tools
RUN python -m pip install --upgrade pip setuptools wheel

# Clone your repo (depth 1 for faster build)
RUN git clone --depth 1 https://github.com/dantelrharrell-debug/Nija.git Nija

# Move into repo
WORKDIR /src/Nija

# Install all .whl files inside the repo automatically
RUN pip install --no-cache-dir $(ls *.whl)

# ---------- Final Stage ----------
FROM python:3.11-slim

# Set working directory for the app
WORKDIR /usr/src/app

# Copy all Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy your bot code
COPY ./bot ./bot

# Copy start script and give execute permissions
COPY start.sh ./
RUN chmod +x start.sh

# Optional: expose ports if needed (for web service)
# EXPOSE 8080

# Set default command
CMD ["./start.sh"]
