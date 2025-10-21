# Use Python 3.11 slim
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y build-essential libssl-dev libffi-dev libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy project files into container
COPY . /app

# Upgrade pip
RUN pip install --upgrade pip

# Install Flask
RUN pip install --no-cache-dir -r requirements.txt

# Expose Flask port
EXPOSE 8080

# Set Flask environment variables
ENV FLASK_APP=nija_bot_web.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=8080

# Start Flask server
CMD ["flask", "run"]
