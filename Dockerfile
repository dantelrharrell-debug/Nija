# Use Python 3.11 slim base (compatible with Coinbase Advanced SDK)
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Expose the port Railway provides
ENV PORT=5000
EXPOSE $PORT

# Start the bot via gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "main:app", "--workers=1", "--threads=2"]
