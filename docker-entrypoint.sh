#!/bin/bash
# Docker entrypoint script for NIJA API
# Handles database initialization and migrations before starting the app

set -e

echo "🚀 NIJA Platform - Starting API Server"
echo "========================================"

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL..."
until python -c "from database.db_connection import init_database, test_connection; init_database(); exit(0 if test_connection() else 1)" 2>/dev/null; do
    echo "   PostgreSQL is unavailable - sleeping"
    sleep 2
done

echo "✅ PostgreSQL is ready"

# Run database migrations
echo "🔄 Running database migrations..."
if alembic upgrade head 2>/dev/null; then
    echo "✅ Database migrations completed"
else
    echo "⚠️  Migrations failed or not configured, continuing..."
fi

# Initialize database if needed (creates tables if they don't exist)
echo "🔧 Initializing database..."
if python init_database.py 2>/dev/null; then
    echo "✅ Database initialized"
else
    echo "⚠️  Database initialization skipped (may already exist)"
fi

echo "========================================"
echo "✨ Starting FastAPI application..."
echo ""

# Execute the main command (passed as arguments)
exec "$@"
