FROM python:3.11-slim

WORKDIR /usr/src/app

# Install git for pip install from GitHub
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install coinbase_advanced_py directly from GitHub (use master branch)
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git@master

# Copy your app code
COPY . .

EXPOSE 5000

# Start Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
