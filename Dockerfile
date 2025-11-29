# Use Python 3.11 slim
FROM python:3.11-slim

# Environment
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# App code
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# Optional cd/ folder
COPY cd/ /app/cd/

# Normalize scripts if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

# Expose port (Railway sets via $PORT)
EXPOSE 8080

# Start Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "web.wsgi:application", \
     "--worker-class", "gthread", "--threads", "2", "--workers", "2", \
     "--timeout", "30", "--log-level", "debug", "--capture-output"]
