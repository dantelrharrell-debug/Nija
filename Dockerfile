# Use Python 3.11 base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy project files into container
COPY . /app

# Upgrade pip
RUN pip install --upgrade pip

# Install Coinbase package directly from GitHub
RUN pip install git+https://github.com/coinbase/coinbase-advanced-py.git@main

# Install Flask and other dependencies from requirements.txt
RUN pip install -r requirements.txt || true

# Expose Flask port
EXPOSE 8080

# Set environment variable for Flask
ENV FLASK_APP=nija_bot_web.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=8080

# Start the Flask app
CMD ["flask", "run"]
