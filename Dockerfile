# Use a stable slim Python image
FROM python:3.11-slim

# Prevent interactive prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system packages required to build and install some Python packages from source
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    gcc \
    libssl-dev \
    libffi-dev \
    python3-dev \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose a port (Railway will override with $PORT at runtime)
ENV PORT=8080
EXPOSE 8080

# Use the start command in railway.json (railway startCommand will override CMD),
# but set a sensible default for local/docker runs:
CMD ["gunicorn", "app.wsgi:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--worker-class", "gthread", "--threads", "2", "--timeout", "120", "--log-level", "debug", "--capture-output"]
