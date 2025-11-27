FROM python:3.11-slim

WORKDIR /app

# System deps for building vendor if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev libffi-dev python3-dev curl \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy source
COPY . /app

# Install requirements if present
RUN if [ -f "requirements.txt" ]; then pip install --no-cache-dir -r requirements.txt; fi

# Install local vendor package (editable)
RUN if [ -d "vendor/coinbase_advanced_py" ]; then pip install --no-cache-dir -e ./vendor/coinbase_advanced_py; fi

# Ensure start script executable
RUN chmod +x /app/start_all.sh

# Add vendor to PYTHONPATH to allow vendor.* imports
ENV PYTHONPATH=/app/vendor:$PYTHONPATH
ENV PORT=8080

EXPOSE 8080

CMD ["./start_all.sh"]
