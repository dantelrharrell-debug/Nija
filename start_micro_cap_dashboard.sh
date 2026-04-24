#!/bin/bash
# NIJA MICRO_CAP Production Readiness Dashboard Startup Script

echo "🚀 Starting NIJA MICRO_CAP Production Readiness Dashboard..."
echo ""

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Set environment variables
export DASHBOARD_PORT="${DASHBOARD_PORT:-5002}"
export FLASK_APP=micro_cap_dashboard_api.py
export FLASK_ENV=production

echo "Dashboard will be available at:"
echo "  📊 Dashboard URL: http://localhost:${DASHBOARD_PORT}/dashboard"
echo "  🔌 API URL: http://localhost:${DASHBOARD_PORT}/api/v1/dashboard/micro-cap"
echo ""

# Start the dashboard API server
python3 micro_cap_dashboard_api.py
