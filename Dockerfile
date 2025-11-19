# Dockerfile
FROM python:3.11-slim

# Install build deps and git (for pip installing from git at runtime)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# copy requirements and install (exclude coinbase-advanced)
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# copy app
COPY . /app

# startup script will pip install coinbase-advanced using GITHUB_PAT then start gunicorn
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 5000

# Start
CMD ["/app/start.sh"]
