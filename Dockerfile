# Base image
ARG PYTHON_VERSION=3.10-slim
FROM python:${PYTHON_VERSION} AS base

WORKDIR /app
COPY . .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Default environment variables
ENV LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1
ENV MODE=production  # default mode

# Set entrypoint
ENTRYPOINT ["sh", "-c"]

# Run command based on MODE environment variable
CMD if [ "$MODE" = "debug" ]; then \
        echo "Starting in debug mode..." && tail -f /dev/null; \
    else \
        echo "Starting preflight and bot..." && python nija_preflight.py && python nija_startup.py; \
    fi
