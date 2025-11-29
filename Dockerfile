# Dockerfile (robust: copy requirements first, then whole context)
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# Install system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker cache
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy the rest of the project in one shot (avoids multiple COPY errors when optional dirs missing)
# Use a single COPY so Docker doesn't fail if an optional subfolder is omitted by CI.
COPY . /app

# Make entrypoint executable and normalize line endings if present
RUN if [ -f /app/entrypoint.sh ]; then dos2unix /app/entrypoint.sh || true; chmod +x /app/entrypoint.sh; fi

# Expose the port your platform will map (Gunicorn will bind to 8080)
EXPOSE 8080

# Use an entrypoint script that runs pre-check and then execs Gunicorn
ENTRYPOINT ["/app/entrypoint.sh"]
