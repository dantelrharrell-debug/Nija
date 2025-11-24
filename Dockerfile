FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Install Python libs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

# Let Python import everything in /app/src
ENV PYTHONPATH=/app/src

EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "src.wsgi:app"]
