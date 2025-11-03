# -----------------------------
# Dockerfile for Nija Trading Bot
# -----------------------------
# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy only requirements first (for caching)
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy the rest of the project files
COPY . .

# Set environment variable for Flask
ENV FLASK_APP=nija_bootstrap.py
ENV LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1

# Expose port (Railway assigns automatically, but default to 10000)
EXPOSE 10000

# Command to run the Flask app via Gunicorn
CMD ["gunicorn", "nija_bootstrap:app", "--workers", "1", "--bind", "0.0.0.0:10000"]
