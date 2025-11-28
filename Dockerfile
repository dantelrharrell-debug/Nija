# Dockerfile
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# system deps you might need (git/build tools)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for cache friendliness (ensure you have requirements.txt at project root)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy entire project into the image
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/
COPY cd/ /app/cd/
# copy other root files if needed (.env, gunicorn.conf.py)
COPY gunicorn.conf.py /app/gunicorn.conf.py
COPY .env /app/.env

# Make sure any shell scripts are LF and executable (if you use start scripts)
RUN if [ -f /app/app/nija_client/start_all.sh ]; then dos2unix /app/app/nija_client/start_all.sh || true; chmod +x /app/app/nija_client/start_all.sh; fi

EXPOSE 8080

# Run Gunicorn pointing to web.wsgi:app
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py", "web.wsgi:app"]
