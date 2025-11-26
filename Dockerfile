# Dockerfile - single-stage, build-time install of Python deps
FROM python:3.11-slim

# make Python output unbuffered (good for logs)
ENV PYTHONUNBUFFERED=1

# Install minimal system packages required to build many Python packages (git + build deps)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      build-essential \
      gcc \
      libssl-dev \
      libffi-dev \
      python3-dev \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker layer cache
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install Python deps at build time so runtime is fast and deterministic
RUN python3 -m pip install --upgrade pip setuptools wheel --root-user-action=ignore \
 && python3 -m pip install --no-cache-dir --root-user-action=ignore -r /app/requirements.txt

# Copy application source after deps installed
COPY . /app

# Ensure startup script is executable
RUN chmod +x /app/start_all.sh || true

# Expose the port your Gunicorn/start script binds to (use 8080 to match our start scripts)
EXPOSE 8080

# Entrypoint / CMD: run safe startup script
CMD ["/app/start_all.sh"]
