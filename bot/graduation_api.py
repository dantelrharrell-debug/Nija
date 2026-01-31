"""
NIJA Graduation API
==================

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

from bot.paper_trading_graduation import (
    PaperTradingGraduationSystem,
    TradingMode,
    GraduationStatus
)
from bot.paper_trading import get_paper_account

logger = logging.getLogger(__name__)

graduation_api = Blueprint('graduation', __name__, url_prefix='/api/graduation')


def get_graduation_system(user_id: str) -> PaperTradingGraduationSystem:
    """Get graduation system for authenticated user"""
    return PaperTradingGraduationSystem(user_id)


@graduation_api.route('/status', methods=['GET'])
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
