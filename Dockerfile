FROM python:3.12-slim

# Avoid cached layers causing version mismatch
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy requirements first to leverage caching
COPY requirements.txt .

# Upgrade pip and install everything
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --upgrade -r requirements.txt

# Copy app last
COPY . .

# Make sure start script is executable
RUN chmod +x ./start_all.sh

CMD ["./start_all.sh"]
