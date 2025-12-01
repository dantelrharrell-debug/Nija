FROM python:3.11-slim

WORKDIR /usr/src/app

# Install system dependencies
RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Make sure vendor folder is present in container for imports
ENV PYTHONPATH="/usr/src/app/cd/vendor:$PYTHONPATH"

# No pip install for coinbase_advanced_py
# COPY cd/vendor/coinbase_advanced_py is enough since PYTHONPATH includes vendor

EXPOSE 5000

# Start Gunicorn pointing to your WSGI app
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
