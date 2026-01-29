"""
NIJA Web Server - Serves Frontend and API

This server combines the REST API backend with the web frontend,
providing a unified entry point for the NIJA platform.
"""

import os
from flask import Flask, send_from_directory
from api_server import app as api_app

# Import mobile API blueprint
from mobile_api import mobile_api

# Register mobile API blueprint
api_app.register_blueprint(mobile_api)

# Configure frontend serving
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), 'frontend')
STATIC_DIR = os.path.join(FRONTEND_DIR, 'static')
TEMPLATE_DIR = os.path.join(FRONTEND_DIR, 'templates')


@api_app.route('/')
def serve_frontend():
    """Serve the main frontend application."""
    return send_from_directory(TEMPLATE_DIR, 'index.html')


@api_app.route('/static/<path:path>')
def serve_static(path):
    """Serve static files (CSS, JS, images)."""
    return send_from_directory(STATIC_DIR, path)


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    print(f"Starting NIJA Platform on port {port}")
    print(f"Frontend: http://localhost:{port}/")
    print(f"API: http://localhost:{port}/api/")
    print(f"Mobile API: http://localhost:{port}/api/mobile/")

    api_app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
