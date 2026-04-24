"""
NIJA Safety Status API - App Store UI Integration
==================================================

This module provides API endpoints for the UI to display all safety features
required for App Store compliance. It exposes the Safety Controller state
to the frontend.

Critical for App Store Review:
- Real-time trading mode status
- Emergency stop state
- Risk acknowledgment status
- Credentials configuration state
- Clear, unambiguous status messages
"""

import os
import logging
import threading
from datetime import datetime
from typing import Dict, Optional
from flask import Blueprint, jsonify, request
from functools import wraps

# Import Safety Controller
try:
    from bot.safety_controller import SafetyController, TradingMode
    from bot.financial_disclaimers import get_user_acknowledgment_text, RISK_DISCLAIMER
except ImportError:
    # Fallback for different import paths
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    from safety_controller import SafetyController, TradingMode
    from financial_disclaimers import get_user_acknowledgment_text, RISK_DISCLAIMER

logger = logging.getLogger(__name__)

# Create API blueprint
safety_api = Blueprint('safety_api', __name__, url_prefix='/api/safety')

# Global safety controller instance (thread-safe)
_safety_controller = None
_safety_controller_lock = threading.Lock()


def get_safety_controller() -> SafetyController:
    """Get or create the global safety controller instance (thread-safe)"""
    global _safety_controller
    if _safety_controller is None:
        with _safety_controller_lock:
            # Double-check locking pattern
            if _safety_controller is None:
                _safety_controller = SafetyController()
    return _safety_controller


def get_risk_acknowledgment_status(user_id: Optional[str] = None) -> Dict:
    """
    Get risk acknowledgment status for a user.
    
    In production, this should check a database for user-specific acknowledgments.
    For now, we check if LIVE_CAPITAL_VERIFIED is set (implicit acknowledgment).
    
    Returns:
        dict: Acknowledgment status with timestamp
    """
    live_verified = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower() in ('true', '1', 'yes')
    
    return {
        'acknowledged': live_verified,
        'timestamp': datetime.utcnow().isoformat() if live_verified else None,
        'required_for_live': True,
        'acknowledgment_text': get_user_acknowledgment_text()
    }


# ========================================
# Safety Status Endpoints
# ========================================

@safety_api.route('/status', methods=['GET'])
def get_safety_status():
    """
    Get comprehensive safety status for UI display.
    
    This is the PRIMARY endpoint for App Store GO CONDITIONS.
    Returns all information needed to display:
    - Trading mode (OFF/DRY RUN/LIVE)
    - Kill-switch state
    - Credentials status
    - Last activity
    - Emergency stop status
    - Risk acknowledgment requirement
    
    Response:
        {
            "mode": "disabled" | "monitor" | "dry_run" | "heartbeat" | "live",
            "mode_display": "Trading OFF — Setup Required",
            "trading_allowed": false,
            "emergency_stop_active": false,
            "credentials_configured": false,
            "last_state_change": "2026-02-03T03:00:00Z",
            "status_message": "Clear human-readable status",
            "requires_risk_acknowledgment": true,
            "risk_acknowledged": false,
            "ui_indicators": {
                "show_simulation_banner": false,
                "status_color": "gray",
                "allow_toggle": false
            }
        }
    """
    try:
        safety = get_safety_controller()
        
        # Get current mode
        mode = safety.get_current_mode()
        mode_value = mode.value if mode else 'disabled'
        
        # Check if trading is allowed
        trading_allowed, reason = safety.is_trading_allowed()
        
        # Get emergency stop status
        emergency_stop = os.path.exists('EMERGENCY_STOP')
        
        # Get credentials status
        credentials_configured = safety._credentials_configured
        
        # Get risk acknowledgment status
        risk_ack = get_risk_acknowledgment_status()
        
        # Determine display message and UI state based on mode
        display_config = get_mode_display_config(mode_value, credentials_configured, emergency_stop)
        
        response = {
            'mode': mode_value,
            'mode_display': display_config['message'],
            'trading_allowed': trading_allowed,
            'trading_allowed_reason': reason,
            'emergency_stop_active': emergency_stop,
            'credentials_configured': credentials_configured,
            'last_state_change': safety._last_state_change,
            'status_message': display_config['status_message'],
            'idle_message': display_config['idle_message'],
            'requires_risk_acknowledgment': risk_ack['required_for_live'],
            'risk_acknowledged': risk_ack['acknowledged'],
            'ui_indicators': display_config['ui_indicators'],
            'app_store_mode': safety.is_app_store_mode(),
            'simulator_allowed': safety.is_simulator_allowed(),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error getting safety status: {e}", exc_info=True)
        return jsonify({
            'error': 'Failed to get safety status',
            'mode': 'disabled',
            'mode_display': 'Trading OFF — Error',
            'trading_allowed': False,
            'emergency_stop_active': False
        }), 500


@safety_api.route('/emergency-stop', methods=['POST'])
def activate_emergency_stop():
    """
    Activate emergency stop - IMMEDIATE trading halt.
    
    This creates the EMERGENCY_STOP file that the bot checks on every cycle.
    Once activated, ALL trading stops immediately.
    
    Request body (optional):
        {
            "reason": "User requested emergency stop"
        }
    
    Response:
        {
            "success": true,
            "message": "Emergency stop activated",
            "timestamp": "2026-02-03T03:00:00Z"
        }
    """
    try:
        data = request.get_json() or {}
        reason = data.get('reason', 'User activated emergency stop via UI')
        
        # Use absolute path for emergency stop file (security best practice)
        emergency_stop_path = os.path.join(os.path.dirname(__file__), 'EMERGENCY_STOP')
        
        # Create emergency stop file with restricted permissions
        with open(emergency_stop_path, 'w') as f:
            f.write(f"Emergency stop activated at {datetime.utcnow().isoformat()}\n")
            f.write(f"Reason: {reason}\n")
            f.write("\nTo resume trading:\n")
            f.write("1. Delete this file\n")
            f.write("2. Restart the bot\n")
        
        # Set restrictive file permissions (owner read/write only)
        os.chmod(emergency_stop_path, 0o600)
        
        logger.warning(f"🚨 EMERGENCY STOP ACTIVATED: {reason}")
        
        return jsonify({
            'success': True,
            'message': 'Emergency stop activated - all trading halted',
            'reason': reason,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error activating emergency stop: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Failed to activate emergency stop'
        }), 500


@safety_api.route('/emergency-stop', methods=['DELETE'])
def deactivate_emergency_stop():
    """
    Deactivate emergency stop - allows trading to resume.
    
    WARNING: Bot must be restarted after removing emergency stop file.
    
    Response:
        {
            "success": true,
            "message": "Emergency stop deactivated",
            "restart_required": true
        }
    """
    try:
        if os.path.exists('EMERGENCY_STOP'):
            os.remove('EMERGENCY_STOP')
            logger.info("Emergency stop file removed")
            
        return jsonify({
            'success': True,
            'message': 'Emergency stop deactivated',
            'restart_required': True,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error deactivating emergency stop: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Failed to deactivate emergency stop'
        }), 500


@safety_api.route('/risk-disclaimer', methods=['GET'])
def get_risk_disclaimer():
    """
    Get the full risk disclaimer text for display.
    
    Response:
        {
            "disclaimer": "Full disclaimer text...",
            "acknowledgment_required": true,
            "acknowledgment_text": "Text user must confirm"
        }
    """
    return jsonify({
        'disclaimer': RISK_DISCLAIMER,
        'acknowledgment_required': True,
        'acknowledgment_text': get_user_acknowledgment_text(),
        'timestamp': datetime.utcnow().isoformat()
    })


@safety_api.route('/acknowledge-risk', methods=['POST'])
def acknowledge_risk():
    """
    Record user's risk acknowledgment.
    
    In production, this should:
    1. Verify user authentication
    2. Store acknowledgment in database with timestamp
    3. Update user permissions
    
    For now, this is informational only. Actual LIVE mode activation
    still requires setting LIVE_CAPITAL_VERIFIED=true in environment.
    
    Request body:
        {
            "user_id": "optional_user_id",
            "acknowledged": true
        }
    
    Response:
        {
            "success": true,
            "message": "Risk acknowledged",
            "next_steps": "Set LIVE_CAPITAL_VERIFIED=true to enable live trading"
        }
    """
    try:
        data = request.get_json() or {}
        
        # In production, validate user and store in database
        # For now, just log it
        logger.info(f"User acknowledged risk: {data}")
        
        return jsonify({
            'success': True,
            'message': 'Risk acknowledgment recorded',
            'timestamp': datetime.utcnow().isoformat(),
            'next_steps': 'To enable live trading, set LIVE_CAPITAL_VERIFIED=true in .env file and restart bot',
            'note': 'Risk acknowledgment is informational. LIVE_CAPITAL_VERIFIED environment variable controls actual live trading.'
        })
        
    except Exception as e:
        logger.error(f"Error recording risk acknowledgment: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Failed to record risk acknowledgment'
        }), 500


# ========================================
# Helper Functions
# ========================================

def get_mode_display_config(mode: str, has_credentials: bool, emergency_stop: bool) -> Dict:
    """
    Get display configuration for a given trading mode.
    
    Returns UI-ready config including:
    - Display message
    - Status message
    - Idle message
    - UI indicators (colors, banners, etc.)
    """
    if emergency_stop:
        return {
            'message': '🚨 EMERGENCY STOP ACTIVE',
            'status_message': 'All trading halted. Delete EMERGENCY_STOP file to resume.',
            'idle_message': 'System stopped. No activity.',
            'ui_indicators': {
                'show_simulation_banner': False,
                'show_emergency_banner': True,
                'status_color': 'red',
                'status_dot': 'red',
                'allow_toggle': False,
                'banner_text': 'EMERGENCY STOP',
                'banner_color': 'red'
            }
        }
    
    if mode == 'disabled':
        if not has_credentials:
            return {
                'message': 'Trading OFF — Setup Required',
                'status_message': 'No exchange credentials configured. App is in safe mode.',
                'idle_message': 'Configure exchange credentials to begin. No trading possible.',
                'ui_indicators': {
                    'show_simulation_banner': False,
                    'show_emergency_banner': False,
                    'status_color': 'gray',
                    'status_dot': 'gray',
                    'allow_toggle': False,
                    'banner_text': 'SETUP REQUIRED',
                    'banner_color': 'gray'
                }
            }
        else:
            return {
                'message': 'Trading OFF',
                'status_message': 'Trading is disabled. Enable in settings to start.',
                'idle_message': 'Monitoring only. No trades active.',
                'ui_indicators': {
                    'show_simulation_banner': False,
                    'show_emergency_banner': False,
                    'status_color': 'gray',
                    'status_dot': 'gray',
                    'allow_toggle': True,
                    'banner_text': None,
                    'banner_color': None
                }
            }
    
    elif mode == 'monitor':
        return {
            'message': 'Monitor Mode — Trading OFF',
            'status_message': 'Displaying market data only. No trades will be executed.',
            'idle_message': 'Monitoring markets. No trades active.',
            'ui_indicators': {
                'show_simulation_banner': False,
                'show_emergency_banner': False,
                'status_color': 'blue',
                'status_dot': 'blue',
                'allow_toggle': True,
                'banner_text': 'MONITOR MODE - NO TRADING',
                'banner_color': 'blue'
            }
        }
    
    elif mode == 'dry_run':
        return {
            'message': 'DRY RUN — Simulation Mode',
            'status_message': 'Simulated trading active. NO real orders placed.',
            'idle_message': 'Simulation running. No real trades.',
            'ui_indicators': {
                'show_simulation_banner': True,
                'show_emergency_banner': False,
                'status_color': 'orange',
                'status_dot': 'orange',
                'allow_toggle': False,
                'banner_text': '🎭 SIMULATION MODE - NO REAL TRADES',
                'banner_color': 'orange'
            }
        }
    
    elif mode == 'app_store':
        return {
            'message': '📱 APP STORE REVIEW MODE',
            'status_message': 'Read-only demonstration mode for App Store reviewers. All dashboards visible, trade buttons disabled.',
            'idle_message': 'Demo mode active. Real trading disabled. Simulator/sandbox trades available.',
            'ui_indicators': {
                'show_simulation_banner': False,
                'show_app_store_banner': True,
                'show_emergency_banner': False,
                'status_color': 'purple',
                'status_dot': 'purple',
                'allow_toggle': False,
                'banner_text': '📱 APP STORE REVIEW MODE - READ-ONLY DEMO',
                'banner_color': 'purple',
                'trade_buttons_disabled': True,
                'simulator_enabled': True
            }
        }
    
    elif mode == 'heartbeat':
        return {
            'message': 'Heartbeat Mode — Verification Trade',
            'status_message': 'Executing single verification trade. Will auto-disable after.',
            'idle_message': 'Heartbeat trade in progress...',
            'ui_indicators': {
                'show_simulation_banner': False,
                'show_emergency_banner': False,
                'status_color': 'yellow',
                'status_dot': 'yellow',
                'allow_toggle': False,
                'banner_text': '💓 HEARTBEAT - SINGLE TEST TRADE',
                'banner_color': 'yellow'
            }
        }
    
    elif mode == 'live':
        return {
            'message': 'LIVE Trading — Active',
            'status_message': 'Real money trading active. Manage positions carefully.',
            'idle_message': 'Monitoring markets. Ready to trade.',
            'ui_indicators': {
                'show_simulation_banner': False,
                'show_emergency_banner': False,
                'status_color': 'green',
                'status_dot': 'green',
                'allow_toggle': True,
                'banner_text': '🟢 LIVE TRADING ACTIVE',
                'banner_color': 'green'
            }
        }
    
    else:
        # Default fallback
        return {
            'message': 'Status Unknown',
            'status_message': 'Unable to determine trading status.',
            'idle_message': 'Monitoring only. No trades active.',
            'ui_indicators': {
                'show_simulation_banner': False,
                'show_emergency_banner': False,
                'status_color': 'gray',
                'status_dot': 'gray',
                'allow_toggle': False,
                'banner_text': None,
                'banner_color': None
            }
        }


# ========================================
# Flask App Integration
# ========================================

def register_safety_api(app):
    """
    Register the safety API blueprint with a Flask app.
    
    Usage:
        from safety_status_api import register_safety_api
        app = Flask(__name__)
        register_safety_api(app)
    """
    app.register_blueprint(safety_api)
    logger.info("Safety Status API registered at /api/safety")


if __name__ == '__main__':
    # Test the API (for development only - NOT for production)
    # Production should use a WSGI server like gunicorn
    from flask import Flask
    
    app = Flask(__name__)
    register_safety_api(app)
    
    print("Safety Status API Test Server")
    print("Endpoints:")
    print("  GET  /api/safety/status")
    print("  POST /api/safety/emergency-stop")
    print("  DELETE /api/safety/emergency-stop")
    print("  GET  /api/safety/risk-disclaimer")
    print("  POST /api/safety/acknowledge-risk")
    print("\nStarting test server on http://localhost:5001")
    print("WARNING: Debug mode disabled for security")
    
    # Never use debug=True in production
    app.run(host='0.0.0.0', port=5001, debug=False)
