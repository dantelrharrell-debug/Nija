# ---------- Builder stage: clone private repo & build wheel ----------
FROM python:3.11-slim AS builder

# Build-time secret (set as Build Argument in Railway)
ARG GITHUB_PAT

# Install git and build deps needed to build wheel
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/build

# Upgrade pip and tools
RUN python -m pip install --upgrade pip setuptools wheel

# Clone the private repo using the x-access-token username (non-interactive)
# NOTE: using the build arg here. This URL will only be visible during build.
RUN git clone --depth 1 "https://x-access-token:${GITHUB_PAT}@github.com/dantelrharrell-debug/coinbase_advanced_py.git" coinbase_advanced_py

# Build wheel for the private package (avoid installing into builder's site-packages)
RUN pip wheel --no-cache-dir --wheel-dir /tmp/wheels /tmp/build/coinbase_advanced_py

# ---------- Final stage: install wheels & app dependencies ----------
FROM python:3.11-slim

ENV PATH="/root/.local/bin:$PATH"
WORKDIR /usr/src/app

# Install system libs required at runtime (minimize footprint)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy wheels built in builder
COPY --from=builder /tmp/wheels /tmp/wheels

# Copy requirements (if you have one)
COPY requirements.txt /usr/src/app/requirements.txt

# Upgrade pip, install requirements and the private wheel(s)
RUN python -m pip install --upgrade pip setuptools wheel && \
    if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt || true; fi && \
    pip install --no-cache-dir /tmp/wheels/* || true

# Copy application code
COPY . /usr/src/app

# Expose port (Railway sets $PORT env variable — your start command must use it)
EXPOSE 8080

# Default command (change as needed)
CMD ["python", "bot/live_trading.py"]
