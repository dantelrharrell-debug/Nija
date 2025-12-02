FROM python:3.11-slim

# Set workdir early
WORKDIR /usr/src/app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install official coinbase SDK (stable public package)
# NOTE: 'coinbase' is the typical package name for Coinbase's public SDKs.
RUN pip install --no-cache-dir coinbase

# Install project requirements (if present)
COPY requirements.txt .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Copy code
COPY . .

# Install dotenv to allow .env usage (optional)
RUN pip install --no-cache-dir python-dotenv

# Make entrypoint executable
RUN chmod +x ./entrypoint.sh

EXPOSE 5000

# Entrypoint runs verification before starting gunicorn
CMD ["./entrypoint.sh"]
