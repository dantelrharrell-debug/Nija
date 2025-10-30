# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /opt/render/project/src

# Copy project files
COPY . .

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip and install Python dependencies (fail build if install fails)
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir coinbase-advanced-py==1.8.2

# Build-time sanity check: is coinbase importable inside the image?
RUN python - <<'PY'
import importlib.util, sys
spec = importlib.util.find_spec("coinbase_advanced_py.client")
print("COINBASE_IMPORTABLE_AT_BUILD:", spec is not None)
if spec is None:
    print("=== BUILD-TIME SYS.PATH ===")
    for p in sys.path:
        print(p)
PY

# Ensure start.sh is executable
RUN chmod +x start.sh

# Expose port if needed (optional)
EXPOSE 8080

# Run bot
CMD ["bash", "start.sh"]
