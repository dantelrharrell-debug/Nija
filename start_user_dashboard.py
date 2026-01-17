#!/usr/bin/env python3
"""
Quick start script for NIJA User Dashboard API

This script starts the dashboard API server and displays the available endpoints.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def print_banner():
    """Print startup banner."""
    print("\n" + "="*70)
    print("NIJA USER DASHBOARD API")
    print("="*70)
    print("\nStarting dashboard API server...")
    print("\n📊 Available Endpoints:")
    print("-" * 70)
    print("User Management:")
    print("  GET  /api/users                     - List all users")
    print("  GET  /api/user/{user_id}/pnl        - Get user PnL dashboard")
    print("  GET  /api/user/{user_id}/risk       - Get user risk status")
    print("  POST /api/user/{user_id}/risk       - Update user risk limits")
    print("\nKill Switches:")
    print("  POST   /api/killswitch/global       - Trigger global kill switch")
    print("  DELETE /api/killswitch/global       - Reset global kill switch")
    print("  POST   /api/killswitch/user/{id}    - Trigger user kill switch")
    print("  DELETE /api/killswitch/user/{id}    - Reset user kill switch")
    print("\nNonce Management:")
    print("  GET  /api/user/{user_id}/nonce      - Get nonce statistics")
    print("  POST /api/user/{user_id}/nonce/reset - Reset nonce tracking")
    print("\nSystem:")
    print("  GET  /api/health                    - Health check")
    print("  GET  /api/stats                     - System statistics")
    print("-" * 70)
    print()


def main():
    """Main entry point."""
    print_banner()
    
    # Get port from environment or use default
    port = int(os.environ.get('DASHBOARD_PORT', 5001))
    host = os.environ.get('DASHBOARD_HOST', '0.0.0.0')
    
    print(f"🚀 Starting server on {host}:{port}")
    print(f"📡 API Base URL: http://localhost:{port}")
    print(f"\n💡 Example: curl http://localhost:{port}/api/users")
    print("\nPress Ctrl+C to stop\n")
    
    # Import and run the dashboard API
    try:
        from bot.user_dashboard_api import run_dashboard_api
        run_dashboard_api(host=host, port=port, debug=False)
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error starting server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
