# Base image
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Copy code
COPY start_bot.py .
COPY nija_client.py .
COPY nija_balance_helper.py .

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables in Docker or via Render dashboard
# ENV COINBASE_PEM_CONTENT=...
# ENV COINBASE_ISS=...
# ENV COINBASE_API_BASE=...

# Run bot
CMD ["python3", "start_bot.py"]
