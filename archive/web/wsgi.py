# web/wsgi.py
# gunicorn should point to web.wsgi:app

from app import create_app

# create_app should return a Flask app instance
app = create_app()
