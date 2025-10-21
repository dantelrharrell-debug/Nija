FROM mcr.microsoft.com/devcontainers/python:3.11

WORKDIR /app
COPY . /app
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt
EXPOSE 5000
CMD ["python3", "nija_bot_web.py"]
