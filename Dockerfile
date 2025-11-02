# Use Python 3.10 for compatibility with coinbase-advancedtrade
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Upgrade pip and install requirements
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Optional: set default environment variables (overridden by Railway)
ENV LOG_LEVEL=INFO

# Command to run preflight and then start bot
CMD ["sh", "-c", "python nija_preflight.py && python nija_startup.py"]
