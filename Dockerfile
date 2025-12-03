FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy your bot code
COPY ./bot ./bot
COPY start.sh ./

# Upgrade pip and install dependencies
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install coinbase_advanced_py==1.8.2

# Make start.sh executable
RUN chmod +x start.sh

# Default entrypoint
CMD ["./start.sh"]
