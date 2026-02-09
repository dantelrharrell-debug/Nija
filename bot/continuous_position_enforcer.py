"""
NIJA Continuous Position Enforcer
==================================

Background service that automatically enforces position caps and cleans up
dust positions for all users at regular intervals.

Key Features:
- Runs continuously in background thread
- Checks all active users every N minutes (default: 5)
- Enforces position caps automatically
- Comprehensive error handling (per-user isolation)
- Graceful shutdown support
- Detailed logging of all actions

Integration:
- Runs alongside main trading bot
- Uses UserPositionReductionEngine for enforcement
- Reads user configs for settings
- Operates independently (won't crash main bot)
"""

import logging
import threading
import time
from typing import Dict, List, Optional
from datetime import datetime
import json
import os

logger = logging.getLogger("nija.position_enforcer")


class ContinuousPositionEnforcer:
    """
    Background service for continuous position cap enforcement.
    
    This runs in a separate thread and periodically checks all users
    for position cap violations and dust positions.
    """
    
    DEFAULT_CHECK_INTERVAL = 300  # 5 minutes in seconds
    DEFAULT_MAX_POSITIONS = 8
    DEFAULT_DUST_THRESHOLD_USD = 1.00
    
    def __init__(
        self,
        reduction_engine,
        user_config_loader,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        max_positions: int = DEFAULT_MAX_POSITIONS,
        dust_threshold_usd: float = DEFAULT_DUST_THRESHOLD_USD,
        enabled: bool = True
    ):
        """
        Initialize continuous position enforcer.
        
        Args:
            reduction_engine: UserPositionReductionEngine instance
            user_config_loader: Function to load user configs
            check_interval: Seconds between enforcement checks
            max_positions: Default max positions per user
            dust_threshold_usd: Default dust threshold
            enabled: Whether enforcement is enabled (can be toggled)
        """
        self.reduction_engine = reduction_engine
        self.user_config_loader = user_config_loader
        self.check_interval = check_interval
        self.default_max_positions = max_positions
        self.default_dust_threshold_usd = dust_threshold_usd
        self.enabled = enabled
        
        # Thread control
        self._thread = None
        self._stop_event = threading.Event()
        self._running = False
        
        # Statistics
        self.stats = {
            'total_runs': 0,
            'total_users_checked': 0,
            'total_positions_closed': 0,
            'last_run': None,
            'errors': []
        }
        
        logger.info(f"Continuous Position Enforcer initialized")
        logger.info(f"  Check interval: {check_interval}s ({check_interval/60:.1f} minutes)")
        logger.info(f"  Default max positions: {max_positions}")
        logger.info(f"  Default dust threshold: ${dust_threshold_usd:.2f}")
        logger.info(f"  Enabled: {enabled}")
    
    def load_user_configs(self) -> List[Dict]:
        """
        Load all user configurations.
        
        Returns:
            List of user config dictionaries
        """
        try:
            if callable(self.user_config_loader):
                return self.user_config_loader()
            else:
                # Fallback: read from config/users directory
                config_dir = os.path.join(os.path.dirname(__file__), '..', 'config', 'users')
                configs = []
                
                if os.path.exists(config_dir):
                    for filename in os.listdir(config_dir):
                        if filename.endswith('.json'):
                            filepath = os.path.join(config_dir, filename)
                            try:
                                with open(filepath, 'r') as f:
                                    config = json.load(f)
                                    # Add user_id from filename if not present
                                    if 'user_id' not in config:
                                        config['user_id'] = filename.replace('.json', '')
                                    configs.append(config)
                            except Exception as e:
                                logger.warning(f"Failed to load config {filename}: {e}")
                
                return configs
        
        except Exception as e:
            logger.error(f"Error loading user configs: {e}")
            return []
    
    def get_user_position_limits(self, user_config: Dict) -> Dict:
        """
        Get position limits for a user from their config.
        
        Args:
            user_config: User configuration dictionary
        
        Returns:
            Dictionary with position limit settings
        """
        # Check for position_limits block in config
        limits = user_config.get('position_limits', {})
        
        return {
            'max_positions': limits.get('max_positions', self.default_max_positions),
            'dust_threshold_usd': limits.get('dust_threshold_usd', self.default_dust_threshold_usd),
            'auto_enforce': limits.get('auto_enforce', True),
            'include_existing_holdings': limits.get('include_existing_holdings', True)
        }
    
    def enforce_for_user(self, user_config: Dict) -> Dict:
        """
        Enforce position limits for a single user.
        
        Args:
            user_config: User configuration dictionary
        
        Returns:
            Enforcement result summary
        """
        user_id = user_config.get('user_id', 'unknown')
        broker_type = user_config.get('broker', user_config.get('broker_type', 'kraken'))
        
        # Check if user is enabled
        if not user_config.get('enabled', False):
            logger.debug(f"Skipping {user_id} - user disabled")
            return {
                'user_id': user_id,
                'skipped': True,
                'reason': 'user_disabled'
            }
        
        # Get position limits
        limits = self.get_user_position_limits(user_config)
        
        # Check if auto enforcement is enabled
        if not limits['auto_enforce']:
            logger.debug(f"Skipping {user_id} - auto_enforce disabled")
            return {
                'user_id': user_id,
                'skipped': True,
                'reason': 'auto_enforce_disabled'
            }
        
        try:
            logger.info(f"Enforcing position limits for {user_id}")
            
            # Run reduction engine
            result = self.reduction_engine.reduce_user_positions(
                user_id=user_id,
                broker_type=broker_type,
                dry_run=False,
                max_positions=limits['max_positions'],
                dust_threshold_usd=limits['dust_threshold_usd']
            )
            
            return result
        
        except Exception as e:
            logger.error(f"Error enforcing for {user_id}: {e}", exc_info=True)
            return {
                'user_id': user_id,
                'error': str(e),
                'success': False
            }
    
    def enforcement_cycle(self):
        """
        Run one enforcement cycle across all users.
        
        This is the main loop that checks all users.
        """
        cycle_start = datetime.now()
        logger.info("=" * 80)
        logger.info(f"Starting enforcement cycle at {cycle_start.isoformat()}")
        logger.info("=" * 80)
        
        # Load user configs
        user_configs = self.load_user_configs()
        logger.info(f"Loaded {len(user_configs)} user configs")
        
        if not user_configs:
            logger.warning("No user configs found - nothing to enforce")
            return
        
        # Track results
        results = []
        total_positions_closed = 0
        errors = []
        
        # Process each user
        for user_config in user_configs:
            try:
                result = self.enforce_for_user(user_config)
                results.append(result)
                
                # Update stats
                if not result.get('skipped') and result.get('closed_positions', 0) > 0:
                    total_positions_closed += result.get('closed_positions', 0)
                    logger.info(
                        f"  ✅ {result['user_id']}: "
                        f"Closed {result['closed_positions']} positions "
                        f"({result['initial_positions']} → {result['final_positions']})"
                    )
            
            except Exception as e:
                logger.error(f"Error processing user {user_config.get('user_id', 'unknown')}: {e}")
                errors.append({
                    'user_id': user_config.get('user_id', 'unknown'),
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
        
        # Update statistics
        self.stats['total_runs'] += 1
        self.stats['total_users_checked'] += len(user_configs)
        self.stats['total_positions_closed'] += total_positions_closed
        self.stats['last_run'] = cycle_start.isoformat()
        
        if errors:
            self.stats['errors'].extend(errors)
            # Keep only last 100 errors
            self.stats['errors'] = self.stats['errors'][-100:]
        
        # Summary
        cycle_duration = (datetime.now() - cycle_start).total_seconds()
        logger.info("=" * 80)
        logger.info(f"Enforcement cycle completed in {cycle_duration:.1f}s")
        logger.info(f"  Users checked: {len(user_configs)}")
        logger.info(f"  Positions closed: {total_positions_closed}")
        logger.info(f"  Errors: {len(errors)}")
        logger.info("=" * 80)
    
    def run_loop(self):
        """
        Main background thread loop.
        
        This runs continuously until stop() is called.
        """
        logger.info("🚀 Position enforcer background loop started")
        
        while not self._stop_event.is_set():
            if self.enabled:
                try:
                    self.enforcement_cycle()
                except Exception as e:
                    logger.error(f"Error in enforcement cycle: {e}", exc_info=True)
            else:
                logger.debug("Enforcement disabled - skipping cycle")
            
            # Wait for next cycle (or until stop event)
            self._stop_event.wait(self.check_interval)
        
        logger.info("🛑 Position enforcer background loop stopped")
    
    def start(self):
        """
        Start the background enforcement thread.
        
        This starts the continuous enforcement loop in a separate thread.
        """
        if self._running:
            logger.warning("Position enforcer already running")
            return
        
        logger.info("Starting position enforcer background thread...")
        
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.run_loop,
            name="PositionEnforcer",
            daemon=True  # Allow main program to exit
        )
        self._thread.start()
        self._running = True
        
        logger.info("✅ Position enforcer started")
    
    def stop(self):
        """
        Stop the background enforcement thread.
        
        This gracefully stops the enforcement loop.
        """
        if not self._running:
            logger.warning("Position enforcer not running")
            return
        
        logger.info("Stopping position enforcer...")
        
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=10)  # Wait up to 10 seconds
            
            if self._thread.is_alive():
                logger.warning("Position enforcer thread did not stop in time")
            else:
                logger.info("✅ Position enforcer stopped")
        
        self._running = False
    
    def is_running(self) -> bool:
        """Check if enforcer is currently running."""
        return self._running
    
    def enable(self):
        """Enable enforcement (will run in next cycle)."""
        self.enabled = True
        logger.info("Position enforcement ENABLED")
    
    def disable(self):
        """Disable enforcement (background thread continues but skips enforcement)."""
        self.enabled = False
        logger.info("Position enforcement DISABLED")
    
    def get_stats(self) -> Dict:
        """
        Get enforcement statistics.
        
        Returns:
            Dictionary with enforcement stats
        """
        return {
            **self.stats,
            'running': self._running,
            'enabled': self.enabled,
            'check_interval': self.check_interval,
            'default_max_positions': self.default_max_positions,
            'default_dust_threshold_usd': self.default_dust_threshold_usd
        }
    
    def trigger_manual_cycle(self):
        """
        Manually trigger an enforcement cycle.
        
        This runs immediately (not in background thread).
        Useful for admin/testing.
        """
        logger.info("Manual enforcement cycle triggered")
        self.enforcement_cycle()


def create_position_enforcer(
    broker_manager,
    portfolio_manager,
    trade_ledger=None,
    user_config_loader=None,
    check_interval: int = ContinuousPositionEnforcer.DEFAULT_CHECK_INTERVAL,
    max_positions: int = ContinuousPositionEnforcer.DEFAULT_MAX_POSITIONS,
    dust_threshold_usd: float = ContinuousPositionEnforcer.DEFAULT_DUST_THRESHOLD_USD,
    auto_start: bool = True
) -> ContinuousPositionEnforcer:
    """
    Factory function to create and optionally start a position enforcer.
    
    Args:
        broker_manager: MultiAccountBrokerManager instance
        portfolio_manager: PortfolioStateManager instance
        trade_ledger: TradeLedger instance (optional)
        user_config_loader: Function to load user configs (optional)
        check_interval: Seconds between checks
        max_positions: Default max positions
        dust_threshold_usd: Default dust threshold
        auto_start: If True, start the enforcer immediately
    
    Returns:
        ContinuousPositionEnforcer instance
    """
    # Import reduction engine
    try:
        from bot.user_position_reduction_engine import UserPositionReductionEngine
    except ImportError:
        from user_position_reduction_engine import UserPositionReductionEngine
    
    # Create reduction engine
    reduction_engine = UserPositionReductionEngine(
        multi_account_broker_manager=broker_manager,
        portfolio_state_manager=portfolio_manager,
        trade_ledger=trade_ledger,
        max_positions=max_positions,
        dust_threshold_usd=dust_threshold_usd
    )
    
    # Create enforcer
    enforcer = ContinuousPositionEnforcer(
        reduction_engine=reduction_engine,
        user_config_loader=user_config_loader,
        check_interval=check_interval,
        max_positions=max_positions,
        dust_threshold_usd=dust_threshold_usd
    )
    
    # Auto-start if requested
    if auto_start:
        enforcer.start()
    
    return enforcer
