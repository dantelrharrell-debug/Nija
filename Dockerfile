FROM python:3.11-slim

# Install git and minimal build deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      build-essential \
      gcc \
      libssl-dev \
      libffi-dev \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY . /usr/src/app

# Upgrade pip, setuptools, wheel
RUN pip install --no-cache-dir -U pip setuptools wheel

# Install requirements
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

EXPOSE 5000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
