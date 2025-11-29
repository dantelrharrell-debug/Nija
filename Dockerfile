# Base image
FROM python:3.11-slim

# Environment
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

# Working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git ca-certificates dos2unix bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy app folders
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/
COPY cd/ /app/cd/   # optional, must exist

# Normalize shell scripts if present
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

# Expose port
EXPOSE 8080

# Gunicorn entrypoint
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "web.wsgi:application", "--worker-class", "gthread", "--threads", "1", "--workers", "2"]
