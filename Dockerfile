# --- Stage 1: builder (uses PAT at build-time only) ---
FROM python:3.11-slim AS builder
ARG GITHUB_PAT
ENV DEBIAN_FRONTEND=noninteractive

# system deps for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# upgrade pip in builder
RUN python -m pip install --upgrade pip setuptools wheel

# If you have a requirements.txt for PyPI packages, optionally build wheels for them here:
# COPY requirements.txt /src/requirements.txt
# RUN pip wheel --no-cache-dir -r /src/requirements.txt -w /wheels

# clone private repo using PAT (non-interactive)
RUN git clone https://$GITHUB_PAT@github.com/dantelrharrell-debug/coinbase_advanced_py.git /src/coinbase_advanced_py

# build a wheel for the private package
WORKDIR /src/coinbase_advanced_py
RUN python -m pip wheel --no-deps --no-cache-dir -w /wheels .

# --- Stage 2: final image ---
FROM python:3.11-slim
ENV PATH="/root/.local/bin:$PATH"
WORKDIR /usr/src/app

# runtime minimal deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# upgrade pip in final image
RUN python -m pip install --upgrade pip setuptools wheel

# copy wheels produced in builder stage
COPY --from=builder /wheels /wheels

# install private wheel(s) and any wheels from requirements (if built)
RUN pip install --no-cache-dir /wheels/* || true

# copy project code
COPY . .

# default port
EXPOSE 8080

# default command (adjust to your entrypoint)
CMD ["python", "bot/live_trading.py"]
