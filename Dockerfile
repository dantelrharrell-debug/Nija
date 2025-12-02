# Use a small official base
FROM python:3.11-slim

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

# Working dir
WORKDIR /usr/src/app

# Install OS packages required for building wheels and git (no recommended extras)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      build-essential \
      ca-certificates \
      curl && \
    rm -rf /var/lib/apt/lists/*

# Defensive: remove any pre-existing shadowing folders (if the build context somehow included them)
RUN rm -rf /usr/src/app/coinbase \
           /usr/src/app/coinbase_advanced \
           /usr/src/app/coinbase-advanced \
           /usr/src/app/coinbase_advanced_py || true

# Copy only requirements first (prevents copying local source that could shadow packages)
COPY requirements.txt .

# Upgrade pip & build tooling
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install the official Coinbase Advanced SDK explicitly (install first to avoid naming confusion)
# Note: we install from the official public repo
RUN python3 -m pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git@master#egg=coinbase_advanced_py

# Install remaining requirements (requirements.txt should NOT contain another git+ line for coinbase)
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Now copy the application source
# Make sure .dockerignore prevents copying any local folders that would shadow pip packages.
COPY . .

# Final defensive cleanup in container filesystem (in case any files were copied inadvertently)
RUN rm -rf ./coinbase \
           ./coinbase_advanced \
           ./coinbase-advanced \
           ./coinbase_advanced_py || true

# Expose port used by Flask/Gunicorn
EXPOSE 5000

# Default command — use your gunicorn conf as before
# If you run the app differently in production adjust this CMD accordingly
CMD ["gunicorn", "-c", "./gunicorn.conf.py", "web.wsgi:app"]
