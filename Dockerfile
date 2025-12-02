# ---------- Builder stage ----------
FROM python:3.11-slim AS builder
ARG GITHUB_PAT

RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/build
RUN python -m pip install --upgrade pip setuptools wheel

# Use Authorization header to authenticate non-interactively
RUN git -c http.extraHeader="Authorization: Bearer ${GITHUB_PAT}" clone --depth 1 https://github.com/dantelrharrell-debug/coinbase_advanced_py.git coinbase_advanced_py

RUN pip wheel --no-cache-dir --wheel-dir /tmp/wheels /tmp/build/coinbase_advanced_py

# ---------- Final stage ----------
FROM python:3.11-slim
WORKDIR /usr/src/app
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /tmp/wheels /tmp/wheels
COPY requirements.txt /usr/src/app/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel \
 && if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt || true; fi \
 && pip install --no-cache-dir /tmp/wheels/* || true

COPY . /usr/src/app
EXPOSE 8080
CMD ["python", "bot/live_trading.py"]
