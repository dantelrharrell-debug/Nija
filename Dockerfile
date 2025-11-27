# Dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PORT=8080

WORKDIR /app

# Copy whole project
COPY . /app

# Install apt deps required to build certain packages (kept minimal)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libssl-dev \
      libffi-dev \
      python3-dev \
      curl \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps if present (requirements.txt optional)
RUN if [ -f "requirements.txt" ]; then pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt; else pip install --upgrade pip; fi

# If you're using pip-installable local vendor package, install it editable:
RUN if [ -d "vendor/coinbase_advanced_py" ]; then pip install --no-cache-dir -e ./vendor/coinbase_advanced_py; fi

# Ensure vendor is on PYTHONPATH so code can import vendor.* packages
ENV PYTHONPATH=/app/vendor:$PYTHONPATH

EXPOSE 8080

# Start script launches the bot (background) then gunicorn
CMD ["./start_all.sh"]
