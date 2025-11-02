# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy all project files into container
COPY . .

# Upgrade pip first
RUN pip install --upgrade pip

# Install all dependencies
RUN pip install -r requirements.txt

# Optional: set default environment variables
ENV LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1

# Start bot (preflight + status + worker all handled in nija_startup.py)
CMD ["python", "nija_startup.py"]
