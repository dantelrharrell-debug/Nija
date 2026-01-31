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
NIJA Graduation API

REST API endpoints for paper trading graduation system.
Provides mobile app and web dashboard with graduation status and controls.

Endpoints:
- GET  /api/graduation/status - Get current graduation progress
- POST /api/graduation/update - Update progress from paper trading stats
- POST /api/graduation/graduate - Graduate to live trading
- POST /api/graduation/unlock-full - Unlock full live trading
- POST /api/graduation/revert-to-paper - Revert to paper trading mode
- GET  /api/graduation/limits - Get current trading limits
"""

from flask import Blueprint, jsonify, request
from typing import Dict
import logging

from bot.paper_trading_graduation import PaperTradingGraduationSystem
from bot.safe_path_resolver import SafePathResolver

logger = logging.getLogger(__name__)

# Create Flask Blueprint
from bot.paper_trading_graduation import (
    PaperTradingGraduationSystem,
    TradingMode,
    GraduationStatus
)
from bot.paper_trading import get_paper_account

logger = logging.getLogger(__name__)

graduation_api = Blueprint('graduation', __name__, url_prefix='/api/graduation')


def get_graduation_system(user_id: str) -> PaperTradingGraduationSystem:
    """
    Get graduation system for authenticated user.
    
    Security:
        - user_id is sanitized using SafePathResolver
        - Runtime security metrics are tracked automatically
    
    Args:
        user_id: User identifier (will be sanitized)
        
    Returns:
        PaperTradingGraduationSystem instance
    """
    # SECURITY: SafePathResolver handles sanitization and tracks metrics
    # No need to sanitize here - PaperTradingGraduationSystem uses SafePathResolver internally
    """Get graduation system for authenticated user"""
    return PaperTradingGraduationSystem(user_id)


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


@graduation_api.route('/security-metrics', methods=['GET'])
def get_security_metrics():
    """
    Get runtime security metrics.
    
    Returns security metrics from SafePathResolver including:
        - Total validations performed
        - Blocked attacks
        - Attack breakdown by type
        - Security score
        
    Returns:
        JSON with security metrics
    """
    try:
        resolver = SafePathResolver.get_instance()
        metrics = resolver.get_metrics()
        
        return jsonify({
            'success': True,
            'data': metrics
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting security metrics: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@graduation_api.route('/security-badge', methods=['GET'])
def get_security_badge():
    """
    Get security badge for monitoring/CI.
    
    Returns:
        Text security badge with current status
    """
    try:
        resolver = SafePathResolver.get_instance()
        badge = resolver.get_security_badge()
        
        return badge, 200, {'Content-Type': 'text/plain; charset=utf-8'}
        
    except Exception as e:
        logger.error(f"Error getting security badge: {e}", exc_info=True)
        return "Error generating security badge", 500
def get_graduation_status():
    """
    Get current graduation progress and status.

    Returns:
        {
            "status": "in_progress",
            "trading_mode": "paper",
            "days_in_paper_trading": 15,
            "criteria": [...],
            "eligible_for_graduation": false,
            "risk_score": 45.0
        }
    """
    try:
        # Get user_id from authentication (mock for now)
        user_id = request.args.get('user_id', 'default_user')

        system = get_graduation_system(user_id)
        criteria = system.get_criteria_details()

        response = {
            'success': True,
            'user_id': user_id,
            'status': system.progress.status.value,
            'trading_mode': system.progress.trading_mode.value,
            'days_in_paper_trading': system.progress.days_in_paper_trading,
            'total_paper_trades': system.progress.total_paper_trades,
            'win_rate': system.progress.win_rate,
            'risk_score': system.progress.risk_score,
            'total_pnl': system.progress.total_pnl,
            'max_drawdown': system.progress.max_drawdown,
            'criteria': [
                {
                    'id': c.criterion_id,
                    'name': c.name,
                    'description': c.description,
                    'met': c.met,
                    'progress': c.progress,
                    'details': c.details
                }
                for c in criteria
            ],
            'eligible_for_graduation': system.is_eligible_for_graduation(),
            'graduation_date': system.progress.graduation_date,
            'live_trading_enabled_date': system.progress.live_trading_enabled_date
        }

        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error getting graduation status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@graduation_api.route('/update', methods=['POST'])
def update_graduation_progress():
    """
    Update graduation progress from current paper trading stats.
    Should be called periodically (e.g., daily) or after significant trades.

    Request Body:
        {
            "user_id": "user123",
            "paper_stats": {
                "total_trades": 25,
                "winning_trades": 15,
                "losing_trades": 10,
                "win_rate": 60.0,
                "total_pnl": 350.0,
                "max_drawdown": 12.5,
                "avg_position_size": 50.0
            }
        }

    Returns:
        {
            "success": true,
            "status": "in_progress",
            "risk_score": 65.0,
            "criteria_met": ["time_requirement", "trade_volume"],
            "criteria_not_met": ["win_rate", "risk_management"]
        }
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'default_user')
        paper_stats = data.get('paper_stats', {})

        system = get_graduation_system(user_id)
        system.update_from_paper_account(paper_stats)

        return jsonify({
            'success': True,
            'user_id': user_id,
            'status': system.progress.status.value,
            'risk_score': system.progress.risk_score,
            'criteria_met': system.progress.criteria_met,
            'criteria_not_met': system.progress.criteria_not_met,
            'eligible_for_graduation': system.is_eligible_for_graduation()
        }), 200

    except Exception as e:
        logger.error(f"Error updating graduation progress: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@graduation_api.route('/graduate', methods=['POST'])
def graduate_to_live_trading():
    """
    Graduate user from paper trading to live trading (with restrictions).

    Request Body:
        {
            "user_id": "user123",
            "acknowledge_risks": true
        }

    Returns:
        {
            "success": true,
            "message": "Congratulations! You have graduated to live trading.",
            "trading_mode": "live_restricted",
            "restrictions": {
                "max_position_size": 100,
                "max_total_capital": 500,
                "unlock_full_after_days": 14
            }
        }
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'default_user')
        acknowledge_risks = data.get('acknowledge_risks', False)

        # Require explicit risk acknowledgment
        if not acknowledge_risks:
            return jsonify({
                'success': False,
                'error': 'Must acknowledge trading risks before graduating to live trading'
            }), 400

        system = get_graduation_system(user_id)
        result = system.graduate_to_live_trading()

        status_code = 200 if result['success'] else 400
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Error graduating user: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@graduation_api.route('/unlock-full', methods=['POST'])
def unlock_full_live_trading():
    """
    Unlock full live trading access (remove restrictions).
    Only available after completing restricted live trading period.

    Request Body:
        {
            "user_id": "user123"
        }

    Returns:
        {
            "success": true,
            "message": "Full live trading access unlocked!",
            "trading_mode": "live_full"
        }
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'default_user')

        system = get_graduation_system(user_id)
        result = system.unlock_full_live_trading()

        status_code = 200 if result['success'] else 400
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Error unlocking full access: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@graduation_api.route('/revert-to-paper', methods=['POST'])
def revert_to_paper_trading():
    """
    Revert user back to paper trading mode.
    Useful for users who want to practice more before risking real capital.

    Request Body:
        {
            "user_id": "user123"
        }

    Returns:
        {
            "success": true,
            "message": "Reverted to paper trading mode",
            "previous_mode": "live_restricted"
        }
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'default_user')

        system = get_graduation_system(user_id)
        result = system.revert_to_paper_trading()

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Error reverting to paper trading: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@graduation_api.route('/limits', methods=['GET'])
def get_trading_limits():
    """
    Get current trading limits based on user's graduation status.

    Returns:
        {
            "mode": "live_restricted",
            "max_position_size": 100,
            "max_total_capital": 500,
            "restrictions": "Limited to $500 total capital"
        }
    """
    try:
        user_id = request.args.get('user_id', 'default_user')

        system = get_graduation_system(user_id)
        limits = system.get_current_limits()

        return jsonify({
            'success': True,
            'user_id': user_id,
            **limits
        }), 200

    except Exception as e:
        logger.error(f"Error getting trading limits: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@graduation_api.route('/sync-from-paper-account', methods=['POST'])
def sync_from_paper_account():
    """
    Sync graduation progress directly from paper trading account.
    Convenience endpoint that reads from paper account and updates graduation.

    Request Body:
        {
            "user_id": "user123"
        }

    Returns:
        {
            "success": true,
            "synced_stats": {...},
            "status": "in_progress"
        }
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'default_user')

        # Get paper account stats
        paper_account = get_paper_account()
        stats = paper_account.get_stats()

        # Update graduation system
        system = get_graduation_system(user_id)
        system.update_from_paper_account(stats)

        return jsonify({
            'success': True,
            'user_id': user_id,
            'synced_stats': stats,
            'status': system.progress.status.value,
            'risk_score': system.progress.risk_score,
            'eligible_for_graduation': system.is_eligible_for_graduation()
        }), 200

    except Exception as e:
        logger.error(f"Error syncing from paper account: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Health check endpoint
@graduation_api.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'graduation_api',
        'version': '1.0.0'
    }), 200
