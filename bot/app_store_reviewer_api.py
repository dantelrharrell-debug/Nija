"""
APP STORE REVIEWER API - Read-Only Endpoints

This module provides read-only API endpoints for Apple App Store reviewers.
These endpoints are always available but are specifically designed to showcase
the app's functionality during review without requiring live trading.

Reviewers can:
- View account balances (simulated or read-only)
- See trading history
- View performance metrics
- Read risk disclosures
- Access dashboard data
- Simulate trading behavior

All endpoints are GET requests (read-only) and do not modify any state.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import os

logger = logging.getLogger("nija.app_store_reviewer_api")


def get_reviewer_welcome_message() -> Dict[str, Any]:
    """
    Get welcome message for Apple reviewers.
    
    Returns:
        Dict: Welcome message and navigation info
    """
    return {
        'message': 'Welcome to NIJA Trading Bot - Apple App Review Mode',
        'app_store_mode': _is_app_store_mode(),
        'features': {
            'dashboard': '/api/reviewer/dashboard',
            'account_info': '/api/reviewer/account',
            'trading_history': '/api/reviewer/history',
            'performance_metrics': '/api/reviewer/performance',
            'risk_disclosures': '/api/reviewer/disclosures',
            'simulation': '/api/reviewer/simulate',
        },
        'note': (
            'All endpoints are read-only. '
            'Live trading is disabled during App Store review. '
            'You can view full UI functionality and simulated behavior.'
        ),
    }


def get_reviewer_dashboard_data() -> Dict[str, Any]:
    """
    Get dashboard data for Apple reviewers.
    
    Returns:
        Dict: Dashboard data (read-only snapshot)
    """
    try:
        # Try to get real data if available
        from bot.dashboard_server import _get_account_manager
        
        manager = _get_account_manager()
        if manager:
            # Get real account summary
            balances = {}
            for broker_type, broker in manager.platform_brokers.items():
                if broker and broker.connected:
                    try:
                        balance = broker.get_account_balance()
                        balances[broker_type.value] = balance
                    except Exception as e:
                        logger.debug(f"Could not fetch {broker_type.value} balance: {e}")
            
            return {
                'status': 'success',
                'mode': 'App Store Review' if _is_app_store_mode() else 'Live',
                'balances': balances,
                'live_trading_enabled': not _is_app_store_mode(),
                'timestamp': datetime.now().isoformat(),
            }
    except Exception as e:
        logger.debug(f"Could not get real dashboard data: {e}")
    
    # Fallback to simulated data for demonstration
    return {
        'status': 'success',
        'mode': 'App Store Review (Simulated)',
        'balances': {
            'kraken': 1250.00,
            'coinbase': 0.00,
        },
        'positions': {
            'open': 3,
            'total_value': 875.50,
        },
        'performance': {
            'today_pnl': 45.30,
            'week_pnl': 123.75,
            'month_pnl': 287.50,
        },
        'live_trading_enabled': not _is_app_store_mode(),
        'timestamp': datetime.now().isoformat(),
        'note': 'Simulated data for App Store review purposes',
    }


def get_reviewer_account_info() -> Dict[str, Any]:
    """
    Get account information for Apple reviewers.
    
    Returns:
        Dict: Account information (read-only)
    """
    return {
        'status': 'success',
        'account': {
            'type': 'Platform Account',
            'balance': {
                'total': 1250.00,
                'available': 374.50,
                'in_positions': 875.50,
            },
            'tier': 'INVESTOR',
            'risk_level': 'MODERATE',
            'max_position_size_pct': 10,
        },
        'connected_exchanges': [
            {
                'name': 'Kraken',
                'status': 'connected',
                'balance': 1250.00,
            },
        ],
        'app_store_mode': _is_app_store_mode(),
        'note': 'Account data is read-only during App Store review',
    }


def get_reviewer_trading_history() -> Dict[str, Any]:
    """
    Get trading history for Apple reviewers.
    
    Returns:
        Dict: Trading history (simulated for review)
    """
    # Generate sample trading history for demonstration
    now = datetime.now()
    sample_trades = [
        {
            'timestamp': (now - timedelta(hours=2)).isoformat(),
            'symbol': 'BTC-USD',
            'side': 'BUY',
            'size': 0.002,
            'price': 42500.00,
            'value': 85.00,
            'status': 'filled',
        },
        {
            'timestamp': (now - timedelta(hours=8)).isoformat(),
            'symbol': 'ETH-USD',
            'side': 'SELL',
            'size': 0.05,
            'price': 2250.00,
            'value': 112.50,
            'pnl': 12.30,
            'status': 'filled',
        },
        {
            'timestamp': (now - timedelta(days=1)).isoformat(),
            'symbol': 'SOL-USD',
            'side': 'BUY',
            'size': 3.5,
            'price': 98.50,
            'value': 344.75,
            'status': 'filled',
        },
    ]
    
    return {
        'status': 'success',
        'trades': sample_trades,
        'total_trades': len(sample_trades),
        'period': '7_days',
        'app_store_mode': _is_app_store_mode(),
        'note': 'Simulated trade history for App Store review demonstration',
    }


def get_reviewer_performance_metrics() -> Dict[str, Any]:
    """
    Get performance metrics for Apple reviewers.
    
    Returns:
        Dict: Performance metrics (simulated for review)
    """
    return {
        'status': 'success',
        'metrics': {
            'total_trades': 47,
            'winning_trades': 28,
            'losing_trades': 19,
            'win_rate': 59.6,
            'total_pnl': 287.50,
            'total_pnl_pct': 23.0,
            'best_trade': {
                'symbol': 'BTC-USD',
                'pnl': 45.80,
                'date': (datetime.now() - timedelta(days=5)).isoformat(),
            },
            'worst_trade': {
                'symbol': 'XRP-USD',
                'pnl': -18.20,
                'date': (datetime.now() - timedelta(days=12)).isoformat(),
            },
            'avg_trade_pnl': 6.12,
            'sharpe_ratio': 1.42,
        },
        'risk_metrics': {
            'max_drawdown': -45.30,
            'max_drawdown_pct': -3.6,
            'volatility': 2.8,
            'risk_per_trade': 2.0,
        },
        'period': '30_days',
        'app_store_mode': _is_app_store_mode(),
        'note': 'Simulated performance metrics for App Store review demonstration',
    }


def get_reviewer_risk_disclosures() -> Dict[str, Any]:
    """
    Get risk disclosures for Apple reviewers.
    
    Returns:
        Dict: Risk disclosures and legal information
    """
    return {
        'status': 'success',
        'disclosures': {
            'independent_trading_model': {
                'title': 'Independent Trading Model',
                'description': (
                    'NIJA operates using an independent trading model. '
                    'Each connected account trades independently using the same '
                    'NIJA trading algorithm. The system does NOT copy, mirror, '
                    'or replicate trades from one account to another.'
                ),
                'points': [
                    'Each account analyzes market data independently',
                    'Each account makes its own trading decisions',
                    'Position sizes are calculated based on account balance',
                    'No account controls or influences other accounts',
                    'Results may differ due to timing and balance variations',
                ],
            },
            'risk_warning': {
                'title': 'Substantial Risk of Loss',
                'description': (
                    'Trading cryptocurrencies involves substantial risk. '
                    'You may lose some or all of your invested capital. '
                    'Only invest money you can afford to lose.'
                ),
                'risks': [
                    'Market volatility can cause rapid price changes',
                    'Algorithmic systems can malfunction or perform poorly',
                    'Exchanges may experience outages or technical issues',
                    'Past performance does not guarantee future results',
                    'No profits are guaranteed',
                ],
            },
            'not_financial_advice': {
                'title': 'Not Financial Advice',
                'description': (
                    'NIJA is a software tool, NOT a financial advisor. '
                    'We do NOT provide investment advice, recommendations, '
                    'or financial planning services.'
                ),
            },
            'user_responsibility': {
                'title': 'User Responsibility',
                'points': [
                    'You maintain full control of your exchange accounts',
                    'You are responsible for all trades executed',
                    'You must monitor your account regularly',
                    'You should understand the strategy before use',
                    'You must comply with all applicable laws',
                ],
            },
        },
        'age_requirement': '18+ (21+ in some jurisdictions)',
        'app_store_mode': _is_app_store_mode(),
        'last_updated': '2026-02-09',
    }


def get_reviewer_simulation_demo() -> Dict[str, Any]:
    """
    Get simulation demo for Apple reviewers.
    Shows how the bot would behave without executing real trades.
    
    Returns:
        Dict: Simulation demo data
    """
    return {
        'status': 'success',
        'simulation': {
            'mode': 'App Store Review Simulation',
            'description': (
                'This demonstrates how NIJA evaluates markets and makes '
                'trading decisions. In App Store mode, NO real orders are placed.'
            ),
            'current_scan': {
                'timestamp': datetime.now().isoformat(),
                'markets_scanned': 732,
                'opportunities_found': 3,
            },
            'sample_signal': {
                'symbol': 'BTC-USD',
                'action': 'BUY',
                'price': 42500.00,
                'size_usd': 85.00,
                'confidence': 0.78,
                'indicators': {
                    'rsi_9': 42.3,
                    'rsi_14': 45.8,
                    'trend': 'BULLISH',
                    'volatility': 'MODERATE',
                },
                'would_execute': True,
                'actual_execution': 'BLOCKED (App Store mode active)',
            },
        },
        'app_store_mode': _is_app_store_mode(),
        'note': (
            'This is a simulation. In App Store review mode, '
            'no real trades are executed regardless of signals.'
        ),
    }


def get_app_store_mode_status() -> Dict[str, Any]:
    """
    Get App Store mode status.
    
    Returns:
        Dict: App Store mode status
    """
    try:
        from bot.app_store_mode import get_app_store_mode
        mode = get_app_store_mode()
        return mode.get_status()
    except ImportError:
        return {
            'app_store_mode': False,
            'error': 'App Store mode module not available',
        }


def get_reviewer_info() -> Dict[str, Any]:
    """
    Get information specifically for Apple reviewers.
    
    Returns:
        Dict: Reviewer information
    """
    try:
        from bot.app_store_mode import get_app_store_mode
        mode = get_app_store_mode()
        return mode.get_reviewer_info()
    except ImportError:
        return {
            'app_store_mode': False,
            'error': 'App Store mode module not available',
            'available_features': {
                'dashboard': True,
                'read_only_api': True,
            },
        }


def _is_app_store_mode() -> bool:
    """
    Check if App Store mode is enabled.
    
    Returns:
        bool: True if App Store mode is active
    """
    try:
        from bot.app_store_mode import is_app_store_mode_enabled
        return is_app_store_mode_enabled()
    except ImportError:
        return False


# Export all reviewer API functions
__all__ = [
    'get_reviewer_welcome_message',
    'get_reviewer_dashboard_data',
    'get_reviewer_account_info',
    'get_reviewer_trading_history',
    'get_reviewer_performance_metrics',
    'get_reviewer_risk_disclosures',
    'get_reviewer_simulation_demo',
    'get_app_store_mode_status',
    'get_reviewer_info',
]
