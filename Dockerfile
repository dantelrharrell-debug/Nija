# Stage 1: Build environment
FROM python:3.11-slim AS builder

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip, setuptools, wheel
RUN python -m pip install --upgrade pip setuptools wheel

# Clone the repo
WORKDIR /src
RUN git clone --depth 1 https://github.com/dantelrharrell-debug/Nija.git Nija
WORKDIR /src/Nija

# Install all wheel dependencies in repo root
COPY ./coinbase_advanced_py-*.whl ./
COPY ./PyJWT-*.whl ./
COPY ./backoff-*.whl ./
COPY ./certifi-*.whl ./
COPY ./cffi-*.whl ./
COPY ./charset_normalizer-*.whl ./
COPY ./cryptography-*.whl ./
COPY ./idna-*.whl ./
COPY ./pycparser-*.whl ./
COPY ./requests-*.whl ./
COPY ./urllib3-*.whl ./
COPY ./websockets-*.whl ./

RUN pip install --no-cache-dir ./*.whl

# Stage 2: Runtime environment
FROM python:3.11-slim

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set working directory
WORKDIR /usr/src/app

# Copy repo code
COPY . .

# Make start script executable
RUN chmod +x start.sh

# Expose port if using web app
EXPOSE 8080

# Entrypoint
CMD ["./start.sh"]
