# Use Python 3.11-slim (Railway/Render compatible)
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Upgrade pip and install requirements
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Optional: set default environment variables (can be overridden in Railway/Render)
ENV LOG_LEVEL=INFO

# Command to run preflight and then start bot
CMD ["sh", "-c", "python nija_preflight.py && python nija_startup.py"]
