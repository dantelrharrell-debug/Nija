# Dockerfile
FROM python:3.11-slim

# create app dir
WORKDIR /usr/src/app

# copy project
COPY . /usr/src/app

# install dependencies
# create a minimal requirements.txt if you don't already have one
RUN pip install --no-cache-dir -U pip setuptools wheel

# If you have requirements.txt in repo, install it.
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# expose port
EXPOSE 5000

# run gunicorn with config file at repo root
CMD ["gunicorn", "--config", "gunicorn.conf.py", "web.wsgi:app"]
