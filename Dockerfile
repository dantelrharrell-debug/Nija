# Dockerfile - minimal, reproducible image for NIJA trading bot
FROM python:3.11-slim

# ensure apt-get noninteractive
ENV DEBIAN_FRONTEND=noninteractive

# working directory
WORKDIR /app

# system deps for building wheels (if necessary) and dos2unix
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git ca-certificates dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# copy only requirements first for better cache
COPY requirements.txt /app/requirements.txt

# Install python deps
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# copy application code
COPY . /app

# Make sure shell scripts are LF and executable
RUN if [ -f ./start_all.sh ]; then dos2unix ./start_all.sh || true; chmod +x ./start_all.sh; fi

# Expose port used by flask/gunicorn
EXPOSE 5000

# Run the startup script
CMD ["./start_all.sh"]
