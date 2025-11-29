# Dockerfile - NIJA Bot (Railway-friendly)
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

WORKDIR /app

# System deps required for cryptography / building wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash libffi-dev libssl-dev pkg-config \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements (for build cache)
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install python deps
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy app and web (these should exist)
COPY app/ /app/app/
COPY web/ /app/web/

# Copy bot only if present in build context (fail-safe: this COPY will only run if bot/ exists)
# If bot/ is missing this will cause build to fail; see below for alternative (BOT_GIT_URL).
# If you want optional cloning, set the build ARG BOT_GIT_URL (see notes).
ARG BOT_GIT_URL=""
RUN if [ -d /tmp/build_bot_marker ]; then echo ""; fi
# Optional: clone bot at build if BOT_GIT_URL provided
RUN if [ -n "$BOT_GIT_URL" ]; then \
      git clone --depth=1 "$BOT_GIT_URL" /app/bot || (echo "bot git clone failed" && false); \
    else \
      echo "No BOT_GIT_URL provided; skipping bot clone"; \
    fi

# Normalize any shell scripts (if present)
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

EXPOSE 8080

# Use explicit module path that exists in this repo
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "web.wsgi:application", \
     "--worker-class", "gthread", "--threads", "1", "--workers", "2", \
     "--log-level", "debug", "--capture-output"]
