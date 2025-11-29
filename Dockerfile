# Dockerfile (robust)
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
# Make sure Python sees /app as import root
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# copy requirements first for cache
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# copy whole project (single COPY avoids missing-path errors)
COPY . /app

# make entrypoint executable if present
RUN if [ -f /app/entrypoint.sh ]; then dos2unix /app/entrypoint.sh || true; chmod +x /app/entrypoint.sh; fi

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
