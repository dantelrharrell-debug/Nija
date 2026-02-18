#!/usr/bin/env python3
"""
Legacy Position Exit Protocol Integration Example
==================================================
Shows how to integrate the Legacy Position Exit Protocol with the main trading bot.

This can be added to:
1. Bot startup sequence (verify/cleanup on start)
2. Scheduled recurring task (e.g., every 6 hours)
3. Manual cleanup trigger
"""

import logging
from pathlib import Path
import sys

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

from bot.position_tracker import PositionTracker
from bot.broker_integration import get_broker_integration
from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol, AccountState

logger = logging.getLogger("nija.integration")


def integrate_with_bot_startup(broker_name='coinbase', max_positions=8, verify_only=True):
    """
    Integration Option 1: Run on Bot Startup
    
    Args:
        broker_name: Broker to use
        max_positions: Maximum allowed positions
        verify_only: If True, only verify state without cleanup
    
    Returns:
        True if account is clean, False if needs cleanup
    """
    logger.info("=" * 80)
    logger.info("STARTUP: Legacy Position Exit Protocol")
    logger.info("=" * 80)
    
    try:
        # Initialize components
        position_tracker = PositionTracker(storage_file="data/positions.json")
        broker = get_broker_integration(broker_name)
        
        protocol = LegacyPositionExitProtocol(
            position_tracker=position_tracker,
            broker_integration=broker,
            max_positions=max_positions,
            stale_order_minutes=30
        )
        
        if verify_only:
            # Just verify state
            state, diagnostics = protocol.verify_clean_state()
            
            if state == AccountState.CLEAN:
                logger.info("✅ Account is clean - proceeding with normal trading")
                return True
            else:
                logger.warning("⚠️  Account needs cleanup")
                logger.warning("Run: python run_legacy_exit_protocol.py")
                return False
        else:
            # Run full cleanup
            results = protocol.run_full_protocol()
            
            if results.get('success'):
                logger.info("✅ Cleanup complete - proceeding with trading")
                return True
            else:
                logger.warning("⚠️  Cleanup incomplete - manual review needed")
                return False
                
    except Exception as e:
        logger.error(f"Error in startup integration: {e}")
        return False


def integrate_as_recurring_task(broker_name='coinbase', max_positions=8, interval_hours=6):
    """
    Integration Option 2: Recurring Background Task
    
    Schedule this to run every N hours to maintain clean state.
    
    Args:
        broker_name: Broker to use
        max_positions: Maximum allowed positions
        interval_hours: How often to run (for scheduling)
    
    Returns:
        Dict with task results
    """
    logger.info("=" * 80)
    logger.info(f"RECURRING TASK: Legacy Position Exit Protocol (every {interval_hours}h)")
    logger.info("=" * 80)
    
    try:
        # Initialize components
        position_tracker = PositionTracker(storage_file="data/positions.json")
        broker = get_broker_integration(broker_name)
        
        protocol = LegacyPositionExitProtocol(
            position_tracker=position_tracker,
            broker_integration=broker,
            max_positions=max_positions,
            stale_order_minutes=30
        )
        
        # First verify if cleanup is needed
        state, diagnostics = protocol.verify_clean_state()
        
        if state == AccountState.CLEAN:
            logger.info("✅ Account is clean - no action needed")
            return {'action': 'none', 'state': 'clean'}
        
        # Run cleanup if needed
        logger.info("⚠️  Running cleanup...")
        results = protocol.run_full_protocol()
        
        return {
            'action': 'cleanup',
            'results': results,
            'success': results.get('success', False)
        }
        
    except Exception as e:
        logger.error(f"Error in recurring task: {e}")
        return {'action': 'error', 'error': str(e)}


def integrate_as_scheduled_cron():
    """
    Integration Option 3: Scheduled via Cron
    
    Add to crontab:
    # Run cleanup every 6 hours
    0 */6 * * * cd /path/to/Nija && python -c "from example_legacy_protocol_integration import integrate_as_recurring_task; integrate_as_recurring_task()"
    
    Or use a scheduling library like APScheduler:
    
    from apscheduler.schedulers.background import BackgroundScheduler
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        integrate_as_recurring_task,
        'interval',
        hours=6,
        args=['coinbase', 8]
    )
    scheduler.start()
    """
    return integrate_as_recurring_task()


def integrate_with_trading_loop(broker_name='coinbase', max_positions=8, check_every_n_cycles=10):
    """
    Integration Option 4: Inline with Trading Loop
    
    Example:
    ```python
    cycle_count = 0
    while trading:
        # Normal trading logic
        scan_markets()
        execute_trades()
        
        # Every N cycles, check cleanup status
        cycle_count += 1
        if cycle_count % check_every_n_cycles == 0:
            from example_legacy_protocol_integration import check_cleanup_status
            if not check_cleanup_status(broker_name, max_positions):
                logger.warning("Account needs cleanup")
    ```
    
    Args:
        broker_name: Broker to use
        max_positions: Maximum allowed positions
        check_every_n_cycles: How often to check
    
    Returns:
        True if account is clean
    """
    try:
        position_tracker = PositionTracker(storage_file="data/positions.json")
        broker = get_broker_integration(broker_name)
        
        protocol = LegacyPositionExitProtocol(
            position_tracker=position_tracker,
            broker_integration=broker,
            max_positions=max_positions
        )
        
        state, _ = protocol.verify_clean_state()
        return state == AccountState.CLEAN
        
    except Exception as e:
        logger.error(f"Error checking cleanup status: {e}")
        return False


def manual_cleanup_trigger(broker_name='coinbase', max_positions=8, user_id=None):
    """
    Integration Option 5: Manual Trigger
    
    Use for:
    - Admin dashboard button
    - API endpoint
    - Support tools
    
    Args:
        broker_name: Broker to use
        max_positions: Maximum allowed positions
        user_id: Optional user ID for multi-account
    
    Returns:
        Dict with cleanup results
    """
    logger.info("=" * 80)
    logger.info("MANUAL TRIGGER: Legacy Position Exit Protocol")
    if user_id:
        logger.info(f"User ID: {user_id}")
    logger.info("=" * 80)
    
    try:
        position_tracker = PositionTracker(storage_file="data/positions.json")
        broker = get_broker_integration(broker_name)
        
        protocol = LegacyPositionExitProtocol(
            position_tracker=position_tracker,
            broker_integration=broker,
            max_positions=max_positions
        )
        
        results = protocol.run_full_protocol(user_id=user_id)
        
        return {
            'success': results.get('success', False),
            'results': results,
            'timestamp': results.get('completed_at')
        }
        
    except Exception as e:
        logger.error(f"Error in manual cleanup: {e}")
        return {'success': False, 'error': str(e)}


# Example Flask API endpoint
def create_cleanup_api_endpoint(app, broker_name='coinbase'):
    """
    Integration Option 6: REST API Endpoint
    
    Add to Flask/FastAPI app:
    ```python
    from flask import Flask, jsonify, request
    
    app = Flask(__name__)
    create_cleanup_api_endpoint(app, 'coinbase')
    ```
    """
    @app.route('/api/cleanup/verify', methods=['GET'])
    def api_verify_cleanup():
        """Verify account cleanup status"""
        try:
            user_id = request.args.get('user_id')
            
            position_tracker = PositionTracker()
            broker = get_broker_integration(broker_name)
            protocol = LegacyPositionExitProtocol(
                position_tracker=position_tracker,
                broker_integration=broker
            )
            
            state, diagnostics = protocol.verify_clean_state(user_id=user_id)
            
            return jsonify({
                'state': state.value,
                'diagnostics': diagnostics
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/cleanup/execute', methods=['POST'])
    def api_execute_cleanup():
        """Execute cleanup protocol"""
        try:
            data = request.get_json() or {}
            user_id = data.get('user_id')
            max_positions = data.get('max_positions', 8)
            
            position_tracker = PositionTracker()
            broker = get_broker_integration(broker_name)
            protocol = LegacyPositionExitProtocol(
                position_tracker=position_tracker,
                broker_integration=broker,
                max_positions=max_positions
            )
            
            results = protocol.run_full_protocol(user_id=user_id)
            
            return jsonify(results)
        except Exception as e:
            return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Example usage
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # Test startup integration
    print("\n1. Testing Startup Integration (verify only)...")
    is_clean = integrate_with_bot_startup(verify_only=True)
    print(f"Result: {'CLEAN' if is_clean else 'NEEDS CLEANUP'}\n")
    
    # Test recurring task
    print("\n2. Testing Recurring Task...")
    result = integrate_as_recurring_task()
    print(f"Result: {result}\n")
    
    # Test inline check
    print("\n3. Testing Inline Check...")
    is_clean = integrate_with_trading_loop()
    print(f"Result: {'CLEAN' if is_clean else 'NEEDS CLEANUP'}\n")
