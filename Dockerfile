# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y build-essential libssl-dev libffi-dev libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . /app

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Ensure start.sh is executable
RUN chmod +x start.sh

# Expose default health port
EXPOSE 10000

# Set environment variables for live trading
ENV COINBASE_API_KEY=f0e7ae67-cf8a-4aee-b3cd-17227a1b8267
ENV COINBASE_API_SECRET=nMHcCAQEEIHVW3T1TLBFLjoNqDOsQjtPtny50auqVT1Y27fIyefOcoAoGCCqGSM49
ENV TV_WEBHOOK_SECRET=your_webhook_secret_here
ENV GITHUB_TOKEN=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
ENV RENDER_API_KEY=rnd_Xiq8UsGVHYyhZfPT3o2xHVNvygQb
ENV RAILWAY_API_KEY=5d2aae31-3b6a-4f3b-a6d6-98b848e24447
ENV BOT_SECRET_KEY=uclgFMvRlYiVOS/HlTihim5V/RYEfuNVClKm3NhdaF9OkZN1BoB/bzN1isZN5RJGBTF/VZBrAB6gPabnisoRtA

# Flask / health server
ENV HEALTH_PORT=${PORT:-10000}
ENV FLASK_APP=nija_bot_web.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=${PORT:-10000}

# Launch start.sh
CMD ["bash", "start.sh"]
