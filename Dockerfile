FROM python:3.11-slim

WORKDIR /app

# Install OS dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy project folders
COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/
COPY cd/ /app/cd/   # <-- cd is at repo root

# Set PYTHONPATH so imports work
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:application"]
