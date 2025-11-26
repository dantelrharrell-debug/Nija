# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required to build some Python packages (do at build time)
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

# Copy app first for dependency caching
COPY requirements.txt .

# Install Python dependencies at build time
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r requirements.txt

# Copy rest of the application
COPY . .

# Make startup script executable
RUN chmod +x ./start_all.sh || true

EXPOSE 5000

CMD ["./start_all.sh"]
