# NIJA Bot Dockerfile - Render/Railway Ready
FROM python:3.11-slim

# Prevent Python buffering
ENV PYTHONUNBUFFERED=1
# Ensure Python can find our packages
ENV PYTHONPATH=/app
# Default port
ENV PORT=8080

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential git ca-certificates dos2unix bash libffi-dev libssl-dev pkg-config \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy project files
COPY gunicorn.conf.py /app/gunicorn.conf.py
COPY web/ /app/web/
COPY app/ /app/app/
COPY bot/ /app/bot/
COPY cd/vendor/ /app/cd/vendor/

# Debug: list files to ensure copy worked
RUN echo "==== /app CONTENTS ====" && ls -R /app

# Normalize shell scripts if present
RUN for f in /app/scripts/start_all.sh /app/start_all.sh; do \
      if [ -f "$f" ]; then dos2unix "$f" && chmod +x "$f"; fi; \
    done

# Expose port
EXPOSE 8080

# Launch Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
