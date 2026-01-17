"""
NIJA Trade Confirmation Webhooks
=================================

Send trade confirmations to user-configured webhook URLs.

Features:
- Per-user webhook URL configuration
- Trade entry/exit notifications
- PnL updates
- Error notifications
- Retry logic for failed webhooks
"""

import os
import json
import logging
import requests
import threading
from typing import Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass, asdict
from queue import Queue
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('nija.webhooks')

# Data directory for webhook config files
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


@dataclass
class WebhookConfig:
    """Webhook configuration for a user."""
    user_id: str
    webhook_url: Optional[str] = None
    enabled: bool = True
    send_entries: bool = True
    send_exits: bool = True
    send_errors: bool = False
    timeout_seconds: int = 5
    max_retries: int = 2
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'WebhookConfig':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class WebhookPayload:
    """Webhook notification payload."""
    event_type: str  # 'trade_entry', 'trade_exit', 'error'
    user_id: str
    timestamp: str
    
    # Trade details
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    size_usd: Optional[float] = None
    
    # Exit details
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    
    # Error details
    error_message: Optional[str] = None
    
    # Context
    strategy: Optional[str] = None
    broker: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {k: v for k, v in asdict(self).items() if v is not None}


class TradeWebhookNotifier:
    """
    Sends trade confirmation webhooks to user endpoints.
    
    Webhooks are sent asynchronously with retry logic.
    """
    
    def __init__(self, max_workers: int = 5):
        """
        Initialize the webhook notifier.
        
        Args:
            max_workers: Maximum concurrent webhook workers
        """
        # Per-user locks for thread-safety
        self._user_locks: Dict[str, threading.Lock] = {}
        
        # Per-user webhook configs
        self._user_configs: Dict[str, WebhookConfig] = {}
        
        # Global lock for manager initialization
        self._manager_lock = threading.Lock()
        
        # Thread pool for async webhook sending
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # Webhook queue
        self._webhook_queue: Queue = Queue()
        
        # Statistics
        self._stats = {
            'total_sent': 0,
            'total_failed': 0,
            'total_retried': 0
        }
        
        # Ensure data directory exists
        os.makedirs(_data_dir, exist_ok=True)
        
        logger.info("TradeWebhookNotifier initialized")
    
    def _get_config_file(self, user_id: str) -> str:
        """Get the config file path for a user."""
        safe_user_id = user_id.replace('/', '_').replace('\\', '_')
        return os.path.join(_data_dir, f"webhook_config_{safe_user_id}.json")
    
    def _get_user_lock(self, user_id: str) -> threading.Lock:
        """Get or create a lock for a user."""
        with self._manager_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.Lock()
            return self._user_locks[user_id]
    
    def _load_config(self, user_id: str) -> WebhookConfig:
        """Load webhook config from file or create defaults."""
        config_file = self._get_config_file(user_id)
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    data = json.load(f)
                    return WebhookConfig.from_dict(data)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load webhook config for {user_id}: {e}, using defaults")
        
        # Return defaults (no webhook URL configured)
        return WebhookConfig(user_id=user_id, webhook_url=None, enabled=False)
    
    def _save_config(self, config: WebhookConfig):
        """Save webhook config to file."""
        config_file = self._get_config_file(config.user_id)
        
        try:
            temp_file = config_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(config.to_dict(), f, indent=2)
            os.replace(temp_file, config_file)
        except IOError as e:
            logger.error(f"Could not save webhook config for {config.user_id}: {e}")
    
    def configure_webhook(
        self,
        user_id: str,
        webhook_url: str,
        enabled: bool = True,
        send_entries: bool = True,
        send_exits: bool = True,
        send_errors: bool = False
    ):
        """
        Configure webhook for a user.
        
        Args:
            user_id: User identifier
            webhook_url: Webhook URL to send notifications to
            enabled: Enable/disable webhook
            send_entries: Send entry notifications
            send_exits: Send exit notifications
            send_errors: Send error notifications
        """
        lock = self._get_user_lock(user_id)
        
        with lock:
            config = WebhookConfig(
                user_id=user_id,
                webhook_url=webhook_url,
                enabled=enabled,
                send_entries=send_entries,
                send_exits=send_exits,
                send_errors=send_errors
            )
            
            self._user_configs[user_id] = config
            self._save_config(config)
            
            logger.info(f"Configured webhook for {user_id}: {webhook_url}")
    
    def get_config(self, user_id: str) -> WebhookConfig:
        """
        Get webhook config for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            WebhookConfig: User's webhook config
        """
        lock = self._get_user_lock(user_id)
        
        with lock:
            if user_id not in self._user_configs:
                self._user_configs[user_id] = self._load_config(user_id)
            return self._user_configs[user_id]
    
    def _send_webhook(self, config: WebhookConfig, payload: WebhookPayload) -> bool:
        """
        Send webhook to user's URL.
        
        Args:
            config: Webhook config
            payload: Payload to send
            
        Returns:
            bool: True if successful
        """
        if not config.webhook_url or not config.enabled:
            return False
        
        try:
            response = requests.post(
                config.webhook_url,
                json=payload.to_dict(),
                timeout=config.timeout_seconds,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code >= 200 and response.status_code < 300:
                logger.debug(f"Webhook sent to {config.user_id}: {payload.event_type}")
                self._stats['total_sent'] += 1
                return True
            else:
                logger.warning(f"Webhook failed for {config.user_id}: HTTP {response.status_code}")
                self._stats['total_failed'] += 1
                return False
        
        except requests.exceptions.Timeout:
            logger.warning(f"Webhook timeout for {config.user_id}")
            self._stats['total_failed'] += 1
            return False
        
        except requests.exceptions.RequestException as e:
            logger.warning(f"Webhook error for {config.user_id}: {e}")
            self._stats['total_failed'] += 1
            return False
    
    def _send_with_retry(self, config: WebhookConfig, payload: WebhookPayload):
        """
        Send webhook with retry logic.
        
        Args:
            config: Webhook config
            payload: Payload to send
        """
        for attempt in range(config.max_retries + 1):
            success = self._send_webhook(config, payload)
            
            if success:
                return
            
            if attempt < config.max_retries:
                logger.debug(f"Retrying webhook for {config.user_id} (attempt {attempt + 2}/{config.max_retries + 1})")
                self._stats['total_retried'] += 1
    
    def notify_trade_entry(
        self,
        user_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        size_usd: float,
        strategy: str = "APEX_v7.1",
        broker: str = "unknown"
    ):
        """
        Send trade entry notification.
        
        Args:
            user_id: User identifier
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Quantity traded
            price: Entry price
            size_usd: Position size in USD
            strategy: Strategy name
            broker: Broker name
        """
        config = self.get_config(user_id)
        
        if not config.enabled or not config.send_entries:
            return
        
        payload = WebhookPayload(
            event_type='trade_entry',
            user_id=user_id,
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            size_usd=size_usd,
            strategy=strategy,
            broker=broker
        )
        
        # Send asynchronously
        self._executor.submit(self._send_with_retry, config, payload)
    
    def notify_trade_exit(
        self,
        user_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        size_usd: float,
        pnl_usd: float,
        pnl_pct: float,
        strategy: str = "APEX_v7.1",
        broker: str = "unknown"
    ):
        """
        Send trade exit notification.
        
        Args:
            user_id: User identifier
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Quantity traded
            price: Exit price
            size_usd: Position size in USD
            pnl_usd: Profit/loss in USD
            pnl_pct: Profit/loss percentage
            strategy: Strategy name
            broker: Broker name
        """
        config = self.get_config(user_id)
        
        if not config.enabled or not config.send_exits:
            return
        
        payload = WebhookPayload(
            event_type='trade_exit',
            user_id=user_id,
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            size_usd=size_usd,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            strategy=strategy,
            broker=broker
        )
        
        # Send asynchronously
        self._executor.submit(self._send_with_retry, config, payload)
    
    def notify_error(
        self,
        user_id: str,
        error_message: str,
        symbol: Optional[str] = None
    ):
        """
        Send error notification.
        
        Args:
            user_id: User identifier
            error_message: Error message
            symbol: Optional symbol related to error
        """
        config = self.get_config(user_id)
        
        if not config.enabled or not config.send_errors:
            return
        
        payload = WebhookPayload(
            event_type='error',
            user_id=user_id,
            timestamp=datetime.now().isoformat(),
            error_message=error_message,
            symbol=symbol
        )
        
        # Send asynchronously
        self._executor.submit(self._send_with_retry, config, payload)
    
    def get_stats(self) -> Dict:
        """
        Get webhook statistics.
        
        Returns:
            dict: Statistics
        """
        return self._stats.copy()
    
    def shutdown(self):
        """Shutdown the webhook notifier."""
        self._executor.shutdown(wait=True)
        logger.info("TradeWebhookNotifier shutdown")


# Global singleton instance
_webhook_notifier: Optional[TradeWebhookNotifier] = None
_init_lock = threading.Lock()


def get_webhook_notifier() -> TradeWebhookNotifier:
    """
    Get the global webhook notifier instance (singleton).
    
    Returns:
        TradeWebhookNotifier: Global instance
    """
    global _webhook_notifier
    
    with _init_lock:
        if _webhook_notifier is None:
            _webhook_notifier = TradeWebhookNotifier()
        return _webhook_notifier


__all__ = [
    'TradeWebhookNotifier',
    'WebhookConfig',
    'WebhookPayload',
    'get_webhook_notifier',
]
