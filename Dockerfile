# Dockerfile - build image that copies app/ into /app
FROM python:3.11-slim

# workdir inside image
WORKDIR /app

# Copy the app package and launcher
COPY app/ ./app/
COPY start_bot.py ./
COPY requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the launcher
CMD ["python3", "start_bot.py"]
