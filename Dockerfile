# --- Stage: builder (create a clean site-packages) ---
FROM python:3.11-slim AS builder

# system deps for building wheels / crypto
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      git \
      libffi-dev \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# upgrade pip tooling
RUN python -m pip install --upgrade pip setuptools wheel

# Copy local wheel(s) and any local whl dependencies into build context
# Make sure coinbase_advanced_py-1.8.2-py3-none-any.whl is in repo root
COPY ./coinbase_advanced_py-1.8.2-py3-none-any.whl ./

# Install only the wheels we ship plus a few runtime deps so final image is ready
RUN pip install --no-cache-dir \
      ./coinbase_advanced_py-1.8.2-py3-none-any.whl \
      PyJWT \
      backoff \
      certifi \
      cffi \
      cryptography \
      idna \
      urllib3 \
      websockets \
      charset_normalizer \
      pycparser

# --- Stage: runtime (final image) ---
FROM python:3.11-slim

WORKDIR /usr/src/app

# Minimal runtime packages that might be needed by cryptography etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      libffi7 || true \
      && rm -rf /var/lib/apt/lists/*

# Copy installed python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app code
# Adjust these to match your repo layout; by default your repo root includes ./bot and start scripts
COPY . .

# Ensure start scripts are executable
RUN chmod +x ./start.sh || true
RUN chmod +x ./start_all.sh || true

# Important env to enable live trading (set LIVE_TRADING in Railway if you want)
ENV LIVE_TRADING=1
ENV PYTHONUNBUFFERED=1

# Expose the port if your web app uses one (adjust if not)
EXPOSE 8080

# Final command: run the orchestrator start script (start_all.sh should exist)
CMD ["./start_all.sh"]
