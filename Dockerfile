# Stage 1: build / install dependencies
FROM python:3.11-slim AS builder

# avoid interactive apt prompts
ENV DEBIAN_FRONTEND=noninteractive

# install system deps needed to build and Wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      build-essential \
      libffi-dev \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Upgrade pip and tools
RUN python -m pip install --upgrade pip setuptools wheel

# Copy local wheel files and any wheels you want installed at build-time
# (Make sure coinbase_advanced_py-1.8.2-py3-none-any.whl is at repo root)
COPY ./coinbase_advanced_py-1.8.2-py3-none-any.whl ./coinbase_advanced_py-1.8.2-py3-none-any.whl
# Optionally copy other local wheels if present:
# COPY ./some_other.whl ./some_other.whl

# Install runtime Python dependencies (including the local wheel)
# Keep this list minimal so the builder caches well. Add more if needed.
RUN python -m pip install --no-cache-dir \
      PyJWT \
      backoff \
      certifi \
      cffi \
      cryptography \
      idna \
      urllib3 \
      websockets \
      charset_normalizer \
      pycparser \
      ./coinbase_advanced_py-1.8.2-py3-none-any.whl

# Stage 2: runtime image
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /usr/src/app

# Copy installed packages from builder to runtime image
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app code
# (assumes your bot folder and start scripts are in repo root)
COPY ./bot ./bot
COPY ./start.sh ./
# If you use start_all.sh or start_bot.sh, copy them as well:
# COPY ./start_all.sh ./

# Make start script executable
RUN chmod +x ./start.sh

# Export the PEM path environment variable default (optional)
ENV LIVE_TRADING=1

# Entrypoint
CMD ["./start.sh"]
