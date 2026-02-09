"""
NIJA User Control Backend - Layer 2 Interface

This module manages user-specific execution instances and communicates
between the public API (Layer 3) and the execution engine (Layer 2).

Key Responsibilities:
- Spawn isolated execution containers per user
- Manage user risk limits and capital allocation
- Route trading commands to correct user instance
- Aggregate statistics from user instances
- Prevent cross-user risk and capital bleed

Architecture:
  [ API Gateway - Layer 3 ]
            ↓
  [ User Control Backend ] ← YOU ARE HERE
            ↓
  [ Execution Engine - Layer 2 ] (one per user or pooled)
            ↓
  [ Core Brain - Layer 1 ] (PRIVATE)
"""

import logging
import os
from typing import Dict, Optional, List
from datetime import datetime
import json

from auth import get_api_key_manager
from execution import get_permission_validator

logger = logging.getLogger(__name__)


class UserExecutionInstance:
    """
    Represents a single user's isolated trading execution instance.

    In production, this would be:
    - A Docker container running NIJA for this user
    - A Kubernetes pod with user-specific config
    - A pooled microservice with user isolation
    """

    def __init__(self, user_id: str, broker_credentials: Dict):
        self.user_id = user_id
        self.broker_credentials = broker_credentials
        self.status = 'stopped'  # stopped, running, paused
        self.created_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.positions = []
        self.stats = {
            'total_trades': 0,
            'total_pnl': 0.0,
            'active_positions': 0
        }

        logger.info(f"🏗️  Created execution instance for user {user_id}")

    def start(self):
        """Start the trading engine for this user."""
        if self.status == 'running':
            return {'success': False, 'message': 'Already running'}

        # TODO: In production, this would:
        # 1. Spin up a Docker container with user-specific config
        # 2. Load user's broker credentials securely
        # 3. Initialize NIJA execution engine with user limits
        # 4. Connect to Layer 1 (Core Brain) for strategy signals

        self.status = 'running'
        self.last_activity = datetime.utcnow()

        logger.info(f"▶️  Started trading for user {self.user_id}")

        return {'success': True, 'message': 'Trading started', 'status': self.status}

    def stop(self):
        """Stop the trading engine for this user."""
        if self.status == 'stopped':
            return {'success': False, 'message': 'Already stopped'}

        # TODO: In production, this would:
        # 1. Gracefully close all open positions
        # 2. Cancel pending orders
        # 3. Shut down the container/process
        # 4. Save final state to database

        self.status = 'stopped'
        self.last_activity = datetime.utcnow()

        logger.info(f"⏹️  Stopped trading for user {self.user_id}")

        return {'success': True, 'message': 'Trading stopped', 'status': self.status}

    def pause(self):
        """Pause the trading engine for this user."""
        if self.status != 'running':
            return {'success': False, 'message': 'Not running'}

        self.status = 'paused'
        self.last_activity = datetime.utcnow()

        logger.info(f"⏸️  Paused trading for user {self.user_id}")

        return {'success': True, 'message': 'Trading paused', 'status': self.status}

    def get_status(self) -> Dict:
        """Get current status of this execution instance."""
        return {
            'user_id': self.user_id,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'stats': self.stats
        }

    def get_positions(self) -> List[Dict]:
        """Get active positions for this user."""
        # TODO: Query actual positions from execution engine
        return self.positions

    def get_stats(self) -> Dict:
        """Get trading statistics for this user."""
        # TODO: Query actual stats from execution engine
        return self.stats
    
    def reduce_positions(
        self,
        broker_type: str = "kraken",
        max_positions: Optional[int] = None,
        dust_threshold_usd: Optional[float] = None,
        dry_run: bool = False
    ) -> Dict:
        """
        Reduce positions for this user.
        
        Args:
            broker_type: Broker type (e.g., 'kraken')
            max_positions: Maximum positions allowed (overrides default)
            dust_threshold_usd: Dust threshold in USD (overrides default)
            dry_run: If True, preview only without executing
        
        Returns:
            Dictionary with reduction results
        """
        try:
            # Import reduction engine
            from bot.user_position_reduction_engine import UserPositionReductionEngine
            from bot.multi_account_broker_manager import MultiAccountBrokerManager
            from bot.portfolio_state import PortfolioStateManager
            
            # Get managers (in production, these would be injected)
            broker_mgr = MultiAccountBrokerManager()
            portfolio_mgr = PortfolioStateManager()
            
            # Create reduction engine
            engine = UserPositionReductionEngine(
                multi_account_broker_manager=broker_mgr,
                portfolio_state_manager=portfolio_mgr,
                trade_ledger=None
            )
            
            # Execute reduction
            result = engine.reduce_user_positions(
                user_id=self.user_id,
                broker_type=broker_type,
                dry_run=dry_run,
                max_positions=max_positions,
                dust_threshold_usd=dust_threshold_usd
            )
            
            # Update stats
            if not dry_run and result.get('closed_positions', 0) > 0:
                self.stats['active_positions'] = result.get('final_positions', 0)
                self.last_activity = datetime.utcnow()
            
            return result
        
        except Exception as e:
            logger.error(f"Error reducing positions for {self.user_id}: {e}")
            return {
                'success': False,
                'error': str(e),
                'user_id': self.user_id
            }


class UserControlBackend:
    """
    Manages all user execution instances and provides the interface
    between Layer 3 (API Gateway) and Layer 2 (Execution Engine).

    Ensures:
    - User isolation (one user cannot affect another)
    - Capital isolation (no cross-user bleeding)
    - Risk enforcement (per-user limits)
    - Strategy protection (Layer 1 remains private)
    """

    def __init__(self):
        self.user_instances: Dict[str, UserExecutionInstance] = {}
        self.api_key_manager = get_api_key_manager()
        self.permission_validator = get_permission_validator()

        logger.info("🎛️  User Control Backend initialized")

    def get_or_create_instance(self, user_id: str) -> UserExecutionInstance:
        """
        Get existing execution instance or create new one for user.

        Args:
            user_id: User identifier

        Returns:
            UserExecutionInstance: User's execution instance
        """
        if user_id not in self.user_instances:
            # Get user's broker credentials
            # In production, this would load from secure storage
            broker_creds = {}

            # Create new instance
            instance = UserExecutionInstance(user_id, broker_creds)
            self.user_instances[user_id] = instance

            logger.info(f"✨ Created new execution instance for user {user_id}")

        return self.user_instances[user_id]

    def start_trading(self, user_id: str) -> Dict:
        """
        Start trading for a user.

        Args:
            user_id: User identifier

        Returns:
            dict: Result of start operation
        """
        # Validate user has permissions
        permissions = self.permission_validator.get_user_permissions(user_id)
        if not permissions or not permissions.enabled:
            return {
                'success': False,
                'error': 'User not enabled or no permissions configured'
            }

        # Get or create execution instance
        instance = self.get_or_create_instance(user_id)

        # Start trading
        result = instance.start()

        return result

    def stop_trading(self, user_id: str) -> Dict:
        """
        Stop trading for a user.

        Args:
            user_id: User identifier

        Returns:
            dict: Result of stop operation
        """
        if user_id not in self.user_instances:
            return {
                'success': False,
                'error': 'No active trading instance found'
            }

        instance = self.user_instances[user_id]
        result = instance.stop()

        return result

    def pause_trading(self, user_id: str) -> Dict:
        """
        Pause trading for a user.

        Args:
            user_id: User identifier

        Returns:
            dict: Result of pause operation
        """
        if user_id not in self.user_instances:
            return {
                'success': False,
                'error': 'No active trading instance found'
            }

        instance = self.user_instances[user_id]
        result = instance.pause()

        return result

    def get_user_status(self, user_id: str) -> Dict:
        """
        Get trading status for a user.

        Args:
            user_id: User identifier

        Returns:
            dict: User's trading status
        """
        if user_id not in self.user_instances:
            return {
                'user_id': user_id,
                'status': 'not_initialized',
                'message': 'No trading instance created yet'
            }

        instance = self.user_instances[user_id]
        return instance.get_status()

    def get_user_positions(self, user_id: str) -> List[Dict]:
        """
        Get active positions for a user.

        Args:
            user_id: User identifier

        Returns:
            list: List of active positions
        """
        if user_id not in self.user_instances:
            return []

        instance = self.user_instances[user_id]
        return instance.get_positions()

    def get_user_stats(self, user_id: str) -> Dict:
        """
        Get trading statistics for a user.

        Args:
            user_id: User identifier

        Returns:
            dict: User's trading statistics
        """
        if user_id not in self.user_instances:
            return {
                'user_id': user_id,
                'total_trades': 0,
                'total_pnl': 0.0,
                'active_positions': 0,
                'message': 'No trading history yet'
            }

        instance = self.user_instances[user_id]
        stats = instance.get_stats()
        stats['user_id'] = user_id

        return stats

    def list_active_instances(self) -> List[str]:
        """
        List all active user instances.

        Returns:
            list: List of user IDs with active instances
        """
        return list(self.user_instances.keys())

    def cleanup_inactive_instances(self, max_idle_hours: int = 24):
        """
        Clean up instances that have been inactive for too long.

        Args:
            max_idle_hours: Maximum idle time in hours before cleanup
        """
        now = datetime.utcnow()
        to_remove = []

        for user_id, instance in self.user_instances.items():
            idle_hours = (now - instance.last_activity).total_seconds() / 3600

            if instance.status == 'stopped' and idle_hours > max_idle_hours:
                to_remove.append(user_id)

        for user_id in to_remove:
            logger.info(f"🧹 Cleaning up inactive instance for user {user_id}")
            del self.user_instances[user_id]

        if to_remove:
            logger.info(f"🧹 Cleaned up {len(to_remove)} inactive instances")


# Global instance
_user_control_backend = UserControlBackend()


def get_user_control_backend() -> UserControlBackend:
    """Get global UserControlBackend instance."""
    return _user_control_backend


__all__ = [
    'UserExecutionInstance',
    'UserControlBackend',
    'get_user_control_backend',
]
