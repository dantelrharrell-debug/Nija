"""
NIJA Independent Broker Trader
================================

This module implements independent trading for each connected brokerage.
Each broker operates in isolation so that failures in one broker don't affect others.

Key Features:
- Each broker runs in its own thread with error isolation
- Independent health monitoring per broker
- Automatic detection of funded brokers
- Graceful degradation on broker failures
- Separate position tracking per broker
"""

import os
import sys
import time
import logging
import threading
from typing import Dict, List, Optional, Set
from datetime import datetime

logger = logging.getLogger("nija.independent_trader")

# Minimum balance required for active trading
MINIMUM_FUNDED_BALANCE = 10.0


class IndependentBrokerTrader:
    """
    Manages independent trading operations across multiple brokers.
    Each broker operates in isolation to prevent cascade failures.
    """
    
    def __init__(self, broker_manager, trading_strategy):
        """
        Initialize independent broker trader.
        
        Args:
            broker_manager: BrokerManager instance with connected brokers
            trading_strategy: TradingStrategy instance for trading logic
        """
        self.broker_manager = broker_manager
        self.trading_strategy = trading_strategy
        
        # Track broker health and status
        self.broker_health: Dict[str, Dict] = {}
        self.broker_threads: Dict[str, threading.Thread] = {}
        self.stop_flags: Dict[str, threading.Event] = {}
        self.funded_brokers: Set[str] = set()
        
        # Thread safety locks
        self.health_lock = threading.Lock()
        
        logger.info("=" * 70)
        logger.info("🔒 INDEPENDENT BROKER TRADER INITIALIZED")
        logger.info("=" * 70)
    
    def detect_funded_brokers(self) -> Dict[str, float]:
        """
        Detect which brokers are funded and ready to trade.
        
        Returns:
            dict: Mapping of broker type name to balance for funded brokers
        """
        funded = {}
        
        logger.info("🔍 Detecting funded brokers...")
        
        for broker_type, broker in self.broker_manager.brokers.items():
            if not broker.connected:
                logger.info(f"   ⚪ {broker_type.value}: Not connected")
                continue
            
            try:
                balance = broker.get_account_balance()
                logger.info(f"   💰 {broker_type.value}: ${balance:,.2f}")
                
                if balance >= MINIMUM_FUNDED_BALANCE:
                    funded[broker_type.value] = balance
                    self.funded_brokers.add(broker_type.value)
                    logger.info(f"      ✅ FUNDED - Ready to trade")
                else:
                    logger.info(f"      ⚠️  Underfunded (minimum: ${MINIMUM_FUNDED_BALANCE:.2f})")
            
            except Exception as e:
                logger.warning(f"   ❌ {broker_type.value}: Error checking balance: {e}")
        
        logger.info("=" * 70)
        if funded:
            logger.info(f"✅ FUNDED BROKERS: {len(funded)}")
            total_capital = sum(funded.values())
            logger.info(f"💰 TOTAL TRADING CAPITAL: ${total_capital:,.2f}")
            for broker_name, balance in funded.items():
                logger.info(f"   • {broker_name}: ${balance:,.2f}")
        else:
            logger.warning("⚠️  NO FUNDED BROKERS DETECTED")
        logger.info("=" * 70)
        
        return funded
    
    def get_broker_health_status(self, broker_name: str) -> Dict:
        """
        Get health status for a specific broker.
        
        Args:
            broker_name: Name of the broker
            
        Returns:
            dict: Health status information
        """
        with self.health_lock:
            return self.broker_health.get(broker_name, {
                'status': 'unknown',
                'last_check': None,
                'error_count': 0,
                'last_error': None,
                'is_trading': False
            })
    
    def update_broker_health(self, broker_name: str, status: str, 
                            error: Optional[str] = None,
                            is_trading: bool = False):
        """
        Update health status for a broker.
        
        Args:
            broker_name: Name of the broker
            status: Health status ('healthy', 'degraded', 'failed')
            error: Optional error message
            is_trading: Whether broker is actively trading
        """
        with self.health_lock:
            if broker_name not in self.broker_health:
                self.broker_health[broker_name] = {
                    'status': status,
                    'last_check': datetime.now(),
                    'error_count': 0,
                    'last_error': None,
                    'is_trading': is_trading,
                    'total_cycles': 0,
                    'successful_cycles': 0
                }
            
            current = self.broker_health[broker_name]
            current['status'] = status
            current['last_check'] = datetime.now()
            current['is_trading'] = is_trading
            current['total_cycles'] = current.get('total_cycles', 0) + 1
            
            if error:
                current['error_count'] = current.get('error_count', 0) + 1
                current['last_error'] = error
                logger.warning(f"⚠️  {broker_name} health degraded: {error}")
            else:
                current['successful_cycles'] = current.get('successful_cycles', 0) + 1
                # Reset error count on success
                if current.get('error_count', 0) > 0:
                    logger.info(f"✅ {broker_name} recovered from errors")
                current['error_count'] = 0
                current['last_error'] = None
    
    def run_broker_trading_loop(self, broker_type, broker, stop_flag: threading.Event):
        """
        Run independent trading loop for a single broker.
        This runs in a separate thread with full error isolation.
        
        Args:
            broker_type: BrokerType enum
            broker: BaseBroker instance
            stop_flag: Threading event to signal stop
        """
        broker_name = broker_type.value
        cycle_count = 0
        
        logger.info(f"🚀 Starting independent trading loop for {broker_name}")
        
        while not stop_flag.is_set():
            cycle_count += 1
            
            try:
                logger.info(f"🔄 {broker_name} - Cycle #{cycle_count}")
                
                # Check if broker is still funded
                try:
                    balance = broker.get_account_balance()
                    if balance < MINIMUM_FUNDED_BALANCE:
                        logger.warning(f"⚠️  {broker_name} balance too low: ${balance:.2f}")
                        self.update_broker_health(broker_name, 'degraded', 
                                                 f'Underfunded: ${balance:.2f}')
                        # Wait before rechecking
                        stop_flag.wait(60)
                        continue
                except Exception as balance_err:
                    logger.error(f"❌ {broker_name} balance check failed: {balance_err}")
                    self.update_broker_health(broker_name, 'degraded', 
                                             f'Balance check failed: {str(balance_err)[:50]}')
                    # Wait before retry
                    stop_flag.wait(30)
                    continue
                
                # Run trading cycle for this broker
                try:
                    # Set this broker as the active broker for the strategy
                    original_broker = self.trading_strategy.broker
                    self.trading_strategy.broker = broker
                    
                    # Execute trading cycle
                    logger.info(f"   {broker_name}: Running trading cycle...")
                    self.trading_strategy.run_cycle()
                    
                    # Restore original broker
                    self.trading_strategy.broker = original_broker
                    
                    # Mark as healthy
                    self.update_broker_health(broker_name, 'healthy', is_trading=True)
                    logger.info(f"   ✅ {broker_name} cycle completed successfully")
                
                except Exception as trading_err:
                    logger.error(f"❌ {broker_name} trading cycle failed: {trading_err}")
                    logger.error(f"   Error type: {type(trading_err).__name__}")
                    
                    # Restore original broker on error
                    try:
                        self.trading_strategy.broker = original_broker
                    except:
                        pass
                    
                    # Update health status
                    self.update_broker_health(broker_name, 'degraded', 
                                             f'Trading error: {str(trading_err)[:100]}')
                    
                    # Continue to next cycle - don't let one broker's failure stop everything
                    logger.info(f"   ⚠️  {broker_name} will retry next cycle")
                
                # Wait 150 seconds (2.5 minutes) between cycles
                # Use stop_flag.wait() so we can be interrupted for shutdown
                logger.info(f"   {broker_name}: Waiting 2.5 minutes until next cycle...")
                stop_flag.wait(150)
            
            except Exception as outer_err:
                # Catch-all for any unexpected errors
                logger.error(f"❌ {broker_name} CRITICAL ERROR in trading loop: {outer_err}")
                self.update_broker_health(broker_name, 'failed', 
                                         f'Critical error: {str(outer_err)[:100]}')
                
                # Wait before retry
                stop_flag.wait(60)
        
        logger.info(f"🛑 {broker_name} trading loop stopped (total cycles: {cycle_count})")
    
    def start_independent_trading(self):
        """
        Start independent trading threads for all funded brokers.
        Each broker operates completely independently.
        """
        logger.info("=" * 70)
        logger.info("🚀 STARTING INDEPENDENT MULTI-BROKER TRADING")
        logger.info("=" * 70)
        
        # Detect funded brokers
        funded = self.detect_funded_brokers()
        
        if not funded:
            logger.error("❌ No funded brokers detected. Cannot start trading.")
            return
        
        # Start a trading thread for each funded broker
        for broker_type, broker in self.broker_manager.brokers.items():
            broker_name = broker_type.value
            
            # Only start threads for funded brokers
            if broker_name not in funded:
                logger.info(f"⏭️  Skipping {broker_name} (not funded)")
                continue
            
            if not broker.connected:
                logger.warning(f"⏭️  Skipping {broker_name} (not connected)")
                continue
            
            # Create stop flag for this broker
            stop_flag = threading.Event()
            self.stop_flags[broker_name] = stop_flag
            
            # Create and start trading thread
            thread = threading.Thread(
                target=self.run_broker_trading_loop,
                args=(broker_type, broker, stop_flag),
                name=f"Trader-{broker_name}",
                daemon=True
            )
            
            self.broker_threads[broker_name] = thread
            thread.start()
            
            logger.info(f"✅ Started independent trading thread for {broker_name}")
        
        logger.info("=" * 70)
        logger.info(f"✅ {len(self.broker_threads)} INDEPENDENT TRADING THREADS RUNNING")
        logger.info("=" * 70)
    
    def stop_all_trading(self):
        """
        Stop all trading threads gracefully.
        """
        logger.info("🛑 Stopping all independent trading threads...")
        
        # Signal all threads to stop
        for broker_name, stop_flag in self.stop_flags.items():
            logger.info(f"   Signaling {broker_name} to stop...")
            stop_flag.set()
        
        # Wait for all threads to finish (with timeout)
        for broker_name, thread in self.broker_threads.items():
            logger.info(f"   Waiting for {broker_name} thread to finish...")
            thread.join(timeout=10)
            if thread.is_alive():
                logger.warning(f"   ⚠️  {broker_name} thread did not stop gracefully")
            else:
                logger.info(f"   ✅ {broker_name} thread stopped")
        
        logger.info("✅ All trading threads stopped")
    
    def get_status_summary(self) -> Dict:
        """
        Get summary of all broker statuses.
        
        Returns:
            dict: Summary of broker health and trading status
        """
        summary = {
            'total_brokers': len(self.broker_manager.brokers),
            'connected_brokers': sum(1 for b in self.broker_manager.brokers.values() if b.connected),
            'funded_brokers': len(self.funded_brokers),
            'trading_threads': len(self.broker_threads),
            'broker_details': {}
        }
        
        with self.health_lock:
            for broker_name, health in self.broker_health.items():
                summary['broker_details'][broker_name] = {
                    'status': health.get('status', 'unknown'),
                    'is_trading': health.get('is_trading', False),
                    'error_count': health.get('error_count', 0),
                    'total_cycles': health.get('total_cycles', 0),
                    'successful_cycles': health.get('successful_cycles', 0),
                    'success_rate': (
                        health.get('successful_cycles', 0) / health.get('total_cycles', 1) * 100
                        if health.get('total_cycles', 0) > 0 else 0
                    )
                }
        
        return summary
    
    def log_status_summary(self):
        """
        Log a summary of all broker trading statuses.
        """
        summary = self.get_status_summary()
        
        logger.info("=" * 70)
        logger.info("📊 MULTI-BROKER TRADING STATUS SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total Brokers: {summary['total_brokers']}")
        logger.info(f"Connected: {summary['connected_brokers']}")
        logger.info(f"Funded: {summary['funded_brokers']}")
        logger.info(f"Active Trading Threads: {summary['trading_threads']}")
        logger.info("")
        
        for broker_name, details in summary['broker_details'].items():
            logger.info(f"{broker_name}:")
            logger.info(f"   Status: {details['status']}")
            logger.info(f"   Trading: {'✅ Yes' if details['is_trading'] else '❌ No'}")
            logger.info(f"   Cycles: {details['successful_cycles']}/{details['total_cycles']} successful")
            logger.info(f"   Success Rate: {details['success_rate']:.1f}%")
            if details['error_count'] > 0:
                logger.info(f"   ⚠️  Recent Errors: {details['error_count']}")
        
        logger.info("=" * 70)
