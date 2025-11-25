# Dockerfile (paste / replace)
FROM python:3.11-slim

# allow passing GH_TOKEN at build time
ARG GH_TOKEN
# Do NOT persist token to final image; we only use it during build and unset it afterwards.

WORKDIR /app

# install system packages needed for git
RUN apt-get update && apt-get install -y git ca-certificates --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# copy only requirements first for better caching
COPY requirements.txt .

# install Python build tools and private repo using GH_TOKEN in same RUN
RUN python -m pip install --upgrade pip setuptools wheel \
  && \
  # install private repo using token, if GH_TOKEN provided. If no GH_TOKEN, this step will still try and fail, so ensure you pass token in build
  /bin/sh -c 'if [ -n "${GH_TOKEN}" ]; then \
      echo "Installing private repo coinbase-advanced using GH_TOKEN"; \
      # install the private repo explicitly using the token
      python -m pip install "git+https://${GH_TOKEN}@github.com/dantelrharrell-debug/coinbase-advanced.git@main"; \
      # install the rest of requirements but exclude coinbase-advanced line so it isn't reattempted
      grep -v -E "coinbase-advanced" requirements.txt > /tmp/reqs_for_pip.txt || true; \
      python -m pip install -r /tmp/reqs_for_pip.txt; \
      # cleanup sensitive temp file
      shred -u /tmp/reqs_for_pip.txt || rm -f /tmp/reqs_for_pip.txt; \
      unset GH_TOKEN || true; \
    else \
      echo "No GH_TOKEN provided; attempting to install all requirements directly (will fail for private repos)"; \
      python -m pip install -r requirements.txt; \
    fi'

# copy app source
COPY . .

# ensure start script is executable (if you use it)
RUN chmod +x ./start_all.sh || true

CMD ["./start_all.sh"]
