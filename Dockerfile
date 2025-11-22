# --- Install system dependencies needed for cryptography and Rust compilation ---
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# --- Install Rust (required for cryptography >= 40.x) ---
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# --- Ensure Rust binaries are in PATH ---
ENV PATH="/root/.cargo/bin:${PATH}"
