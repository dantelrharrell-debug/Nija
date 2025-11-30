# ---- Base Image ----
FROM python:3.11-slim

# ---- Set Working Directory ----
WORKDIR /app

# ---- Install System Dependencies ----
RUN apt-get update && \
    apt-get install -y git build-essential && \
    rm -rf /var/lib/apt/lists/*

# ---- Copy Requirements ----
COPY requirements.txt .

# ---- Install Python Dependencies ----
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---- Copy Project Files ----
COPY . .

# ---- Make Entrypoint Executable ----
RUN chmod +x ./entrypoint.sh

# ---- Expose Port for Gunicorn ----
EXPOSE 5000

# ---- Entrypoint ----
ENTRYPOINT ["bash", "-lc", "./entrypoint.sh"]
