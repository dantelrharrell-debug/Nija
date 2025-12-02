# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

# Basic system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      build-essential \
      ca-certificates \
      openssh-client \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

# upgrade pip
RUN python -m pip install --upgrade pip setuptools wheel

# copy only requirements first to leverage cache
COPY requirements.txt .

# install normal PyPI deps
RUN pip install --no-cache-dir -r requirements.txt

# >>> Install private repo via SSH using BuildKit SSH mount <<<
# This reads the SSH agent/key from the build environment and uses git+ssh.
# Note: BuildKit must be enabled when building (DOCKER_BUILDKIT=1)
RUN --mount=type=ssh pip install --no-cache-dir \
    git+ssh://git@github.com/dantelrharrell-debug/coinbase_advanced_py.git@main#egg=coinbase_advanced_py || \
    (echo "warning: coinbase_advanced_py failed to install (continuing)"; exit 0)

# copy app code
COPY . .

# expose port if needed
EXPOSE 8080

# default command — change to how you run your bot
CMD ["python", "bot/live_trading.py"]
