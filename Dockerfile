# Dockerfile — place at repo root (replace existing)
FROM python:3.11-slim

# set working dir
WORKDIR /usr/src/app

# Reduce interactive prompts and install system deps used for building wheels
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        ca-certificates \
        curl && \
    rm -rf /var/lib/apt/lists/*

# Copy only requirements first to avoid shadowing issues
COPY requirements.txt ./

# Make sure we don't have repo shadowing in build context (defensive)
# (This won't remove anything from the host—only inside the image)
RUN rm -rf /usr/src/app/coinbase \
           /usr/src/app/coinbase_advanced \
           /usr/src/app/coinbase-advanced \
           /usr/src/app/coinbase_advanced_py || true

# Upgrade pip & tooling
RUN python3 -m pip install --upgrade pip setuptools wheel

# Install the official Coinbase Advanced SDK first (explicit)
RUN python3 -m pip install --no-cache-dir --force-reinstall \
    git+https://github.com/coinbase/coinbase-advanced-py.git@master#egg=coinbase_advanced_py

# Then install the rest of the requirements (requirements.txt should NOT contain coinbase git line)
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Copy the rest of app files
COPY . .

# Final cleanup: remove any repo-provided shadowing folders so they can't mask site-packages
RUN rm -rf ./coinbase \
           ./coinbase_advanced \
           ./coinbase-advanced \
           ./coinbase_advanced_py || true

# Default command — use your existing start or gunicorn command
# If you have start.sh:
CMD ["./start.sh"]
# Or, to run gunicorn directly:
# CMD ["python3", "-m", "gunicorn", "-c", "./gunicorn.conf.py", "web.wsgi:app"]
