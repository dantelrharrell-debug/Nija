# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make sure shell script is executable
RUN chmod +x start_all.sh

# Set container entrypoint
ENTRYPOINT ["./start_all.sh"]
