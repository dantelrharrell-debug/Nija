"""
Graduation API for Paper Trading Graduation System

Flask Blueprint providing REST API endpoints for managing user progression
through paper trading to live trading graduation.

Security Features:
    - Input validation on all user-provided data
    - Sanitization of user_id to prevent path traversal
    - Rate limiting ready endpoints
    - Proper error handling without information leakage

API Endpoints:
    - GET  /api/graduation/status - Get graduation status for a user
    - GET  /api/graduation/limits - Get current trading limits
    - GET  /api/graduation/criteria - Get graduation criteria details
    - POST /api/graduation/update-metrics - Update trading metrics
    - POST /api/graduation/graduate - Attempt graduation to next level

Author: NIJA Trading Systems
Date: January 31, 2026
"""

from flask import Blueprint, jsonify, request
from typing import Dict
import logging

from bot.paper_trading_graduation import PaperTradingGraduationSystem
from bot.path_validator import sanitize_filename

logger = logging.getLogger(__name__)

# Create Flask Blueprint
graduation_api = Blueprint('graduation', __name__, url_prefix='/api/graduation')


def get_graduation_system(user_id: str) -> PaperTradingGraduationSystem:
    """
    Get graduation system for authenticated user.
    
    Security:
        - user_id is sanitized in PaperTradingGraduationSystem.__init__
        - Additional validation here for defense in depth
    
    Args:
        user_id: User identifier (will be sanitized)
        
    Returns:
        PaperTradingGraduationSystem instance
    """
    # SECURITY: Sanitize user_id before creating system
    # This is defense in depth - PaperTradingGraduationSystem also sanitizes
    safe_user_id = sanitize_filename(user_id)
    
    return PaperTradingGraduationSystem(safe_user_id)


@graduation_api.route('/status', methods=['GET'])
def get_status():
    """
    Get graduation status for a user.
    
    Query Parameters:
        user_id: User identifier (optional, defaults to 'default_user')
        
    Returns:
        JSON with graduation status
        
    Security:
        - user_id parameter is sanitized before use
        - No sensitive information in error messages
    """
    try:
        # SECURITY: Get user_id from authentication (mock for now)
        # In production, this would come from authenticated session
        user_id = request.args.get('user_id', 'default_user')
        
        # SECURITY: Additional validation - ensure user_id is not empty
        if not user_id or not isinstance(user_id, str):
            return jsonify({
                'success': False,
                'error': 'Invalid user_id parameter'
            }), 400
        
        system = get_graduation_system(user_id)
        status = system.get_status()
        
        return jsonify({
            'success': True,
            'data': status
        }), 200
        
    except ValueError as e:
        # Security validation failed
        logger.warning(f"Validation error in get_status: {e}")
        return jsonify({
            'success': False,
            'error': 'Invalid request parameters'
        }), 400
        
    except Exception as e:
        # Don't leak internal error details
        logger.error(f"Error in get_status: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@graduation_api.route('/limits', methods=['GET'])
def get_limits():
    """
    Get current trading limits based on graduation level.
    
    Query Parameters:
        user_id: User identifier (optional, defaults to 'default_user')
        
    Returns:
        JSON with trading limits
        
    Security:
        - user_id parameter is sanitized before use
    """
    try:
        # SECURITY: Get user_id from query params with validation
        user_id = request.args.get('user_id', 'default_user')
        
        if not user_id or not isinstance(user_id, str):
            return jsonify({
                'success': False,
                'error': 'Invalid user_id parameter'
            }), 400
        
        system = get_graduation_system(user_id)
        limits = system.get_current_limits()
        
        return jsonify({
            'success': True,
            'data': limits
        }), 200
        
    except ValueError as e:
        logger.warning(f"Validation error in get_limits: {e}")
        return jsonify({
            'success': False,
            'error': 'Invalid request parameters'
        }), 400
        
    except Exception as e:
        logger.error(f"Error in get_limits: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@graduation_api.route('/criteria', methods=['GET'])
def get_criteria():
    """
    Get detailed graduation criteria and progress.
    
    Query Parameters:
        user_id: User identifier (optional, defaults to 'default_user')
        
    Returns:
        JSON with criteria details and current progress
        
    Security:
        - user_id parameter is sanitized before use
    """
    try:
        # SECURITY: Validate and sanitize user_id
        user_id = request.args.get('user_id', 'default_user')
        
        if not user_id or not isinstance(user_id, str):
            return jsonify({
                'success': False,
                'error': 'Invalid user_id parameter'
            }), 400
        
        system = get_graduation_system(user_id)
        criteria = system.get_criteria_details()
        
        return jsonify({
            'success': True,
            'data': criteria
        }), 200
        
    except ValueError as e:
        logger.warning(f"Validation error in get_criteria: {e}")
        return jsonify({
            'success': False,
            'error': 'Invalid request parameters'
        }), 400
        
    except Exception as e:
        logger.error(f"Error in get_criteria: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@graduation_api.route('/update-metrics', methods=['POST'])
def update_metrics():
    """
    Update trading performance metrics for a user.
    
    Request Body (JSON):
        {
            "user_id": "user123",
            "metrics": {
                "total_trades": 50,
                "win_rate": 0.55,
                "sharpe_ratio": 1.2,
                "max_drawdown": 0.12,
                "profit_factor": 1.5,
                "avg_risk_reward": 1.8
            }
        }
        
    Returns:
        JSON with success status and updated criteria
        
    Security:
        - Validates all input parameters
        - Sanitizes user_id
        - Validates metric values are numeric
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body required'
            }), 400
        
        # SECURITY: Validate user_id
        user_id = data.get('user_id')
        if not user_id or not isinstance(user_id, str):
            return jsonify({
                'success': False,
                'error': 'Invalid user_id'
            }), 400
        
        # SECURITY: Validate metrics
        metrics = data.get('metrics')
        if not metrics or not isinstance(metrics, dict):
            return jsonify({
                'success': False,
                'error': 'Invalid metrics data'
            }), 400
        
        # Validate metric values are numeric
        required_fields = ['total_trades', 'win_rate', 'sharpe_ratio', 
                          'max_drawdown', 'profit_factor', 'avg_risk_reward']
        
        for field in required_fields:
            if field not in metrics:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
            
            try:
                float(metrics[field])
            except (ValueError, TypeError):
                return jsonify({
                    'success': False,
                    'error': f'Invalid value for {field}'
                }), 400
        
        # Update metrics
        system = get_graduation_system(user_id)
        system.update_metrics(metrics)
        
        # Return updated criteria
        criteria = system.get_criteria_details()
        
        return jsonify({
            'success': True,
            'data': {
                'criteria': criteria,
                'ready_for_graduation': system.is_ready_for_restricted_live()
            }
        }), 200
        
    except ValueError as e:
        logger.warning(f"Validation error in update_metrics: {e}")
        return jsonify({
            'success': False,
            'error': 'Invalid request parameters'
        }), 400
        
    except Exception as e:
        logger.error(f"Error in update_metrics: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@graduation_api.route('/graduate', methods=['POST'])
def graduate_user():
    """
    Attempt to graduate user to next level.
    
    Request Body (JSON):
        {
            "user_id": "user123",
            "target_level": "restricted_live"  # or "full_live"
        }
        
    Returns:
        JSON with graduation result
        
    Security:
        - Validates user_id and target_level
        - Checks graduation criteria before allowing progression
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body required'
            }), 400
        
        # SECURITY: Validate user_id
        user_id = data.get('user_id')
        if not user_id or not isinstance(user_id, str):
            return jsonify({
                'success': False,
                'error': 'Invalid user_id'
            }), 400
        
        # Validate target level
        target_level = data.get('target_level')
        if target_level not in ['restricted_live', 'full_live']:
            return jsonify({
                'success': False,
                'error': 'Invalid target_level. Must be "restricted_live" or "full_live"'
            }), 400
        
        system = get_graduation_system(user_id)
        
        # Attempt graduation
        if target_level == 'restricted_live':
            success = system.graduate_to_restricted_live()
            message = "Graduated to restricted live trading" if success else "Criteria not met for restricted live"
        else:  # full_live
            success = system.graduate_to_full_live()
            message = "Graduated to full live trading" if success else "Criteria not met for full live"
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'new_level': system.progress.level,
                'limits': system.get_current_limits()
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': message,
                'current_level': system.progress.level,
                'criteria': system.get_criteria_details()
            }), 400
        
    except ValueError as e:
        logger.warning(f"Validation error in graduate_user: {e}")
        return jsonify({
            'success': False,
            'error': 'Invalid request parameters'
        }), 400
        
    except Exception as e:
        logger.error(f"Error in graduate_user: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@graduation_api.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'success': True,
        'service': 'graduation_api',
        'status': 'healthy'
    }), 200
