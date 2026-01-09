"""
NIJA Multi-Account Broker Manager
==================================

Manages separate trading accounts for:
- MASTER account: Nija system trading account
- USER accounts: Individual user/investor accounts

Each account trades independently with its own:
- API credentials
- Trading balance
- Position tracking
- Risk limits
"""

import logging
from typing import Dict, List, Optional
from enum import Enum

# Import broker classes
from broker_manager import (
    BrokerType, AccountType, BaseBroker,
    CoinbaseBroker, KrakenBroker, OKXBroker, AlpacaBroker
)

logger = logging.getLogger('nija.multi_account')


class MultiAccountBrokerManager:
    """
    Manages brokers for multiple accounts (master + users).
    
    Each account can have connections to multiple exchanges.
    Accounts are completely isolated from each other.
    """
    
    def __init__(self):
        """Initialize multi-account broker manager."""
        # Master account brokers
        self.master_brokers: Dict[BrokerType, BaseBroker] = {}
        
        # User account brokers - structure: {user_id: {BrokerType: BaseBroker}}
        self.user_brokers: Dict[str, Dict[BrokerType, BaseBroker]] = {}
        
        logger.info("=" * 70)
        logger.info("🔒 MULTI-ACCOUNT BROKER MANAGER INITIALIZED")
        logger.info("=" * 70)
    
    def add_master_broker(self, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Add a broker for the master (Nija system) account.
        
        Args:
            broker_type: Type of broker to add (COINBASE, KRAKEN, etc.)
            
        Returns:
            BaseBroker instance or None if failed
        """
        try:
            broker = None
            
            if broker_type == BrokerType.COINBASE:
                broker = CoinbaseBroker()
            elif broker_type == BrokerType.KRAKEN:
                broker = KrakenBroker(account_type=AccountType.MASTER)
            elif broker_type == BrokerType.OKX:
                broker = OKXBroker()
            elif broker_type == BrokerType.ALPACA:
                broker = AlpacaBroker()
            else:
                logger.warning(f"⚠️  Unsupported broker type for master: {broker_type.value}")
                return None
            
            # Connect the broker
            if broker.connect():
                self.master_brokers[broker_type] = broker
                logger.info(f"✅ Master broker added: {broker_type.value}")
                return broker
            else:
                logger.warning(f"⚠️  Failed to connect master broker: {broker_type.value}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error adding master broker {broker_type.value}: {e}")
            return None
    
    def add_user_broker(self, user_id: str, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Add a broker for a user account.
        
        Args:
            user_id: User identifier (e.g., 'daivon_frazier')
            broker_type: Type of broker to add
            
        Returns:
            BaseBroker instance or None if failed
        """
        try:
            broker = None
            
            if broker_type == BrokerType.KRAKEN:
                broker = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
            else:
                logger.warning(f"⚠️  Unsupported broker type for user: {broker_type.value}")
                logger.warning(f"   Only KRAKEN is currently supported for user accounts")
                return None
            
            # Connect the broker
            if broker.connect():
                if user_id not in self.user_brokers:
                    self.user_brokers[user_id] = {}
                
                self.user_brokers[user_id][broker_type] = broker
                logger.info(f"✅ User broker added: {user_id} -> {broker_type.value}")
                return broker
            else:
                logger.warning(f"⚠️  Failed to connect user broker: {user_id} -> {broker_type.value}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error adding user broker {broker_type.value} for {user_id}: {e}")
            return None
    
    def get_master_broker(self, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Get a master account broker.
        
        Args:
            broker_type: Type of broker to get
            
        Returns:
            BaseBroker instance or None if not found
        """
        return self.master_brokers.get(broker_type)
    
    def get_user_broker(self, user_id: str, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Get a user account broker.
        
        Args:
            user_id: User identifier
            broker_type: Type of broker to get
            
        Returns:
            BaseBroker instance or None if not found
        """
        user_brokers = self.user_brokers.get(user_id, {})
        return user_brokers.get(broker_type)
    
    def get_master_balance(self, broker_type: Optional[BrokerType] = None) -> float:
        """
        Get master account balance.
        
        Args:
            broker_type: Specific broker or None for total across all brokers
            
        Returns:
            Balance in USD
        """
        if broker_type:
            broker = self.master_brokers.get(broker_type)
            return broker.get_account_balance() if broker else 0.0
        
        # Total across all master brokers
        total = 0.0
        for broker in self.master_brokers.values():
            if broker.connected:
                total += broker.get_account_balance()
        return total
    
    def get_user_balance(self, user_id: str, broker_type: Optional[BrokerType] = None) -> float:
        """
        Get user account balance.
        
        Args:
            user_id: User identifier
            broker_type: Specific broker or None for total across all brokers
            
        Returns:
            Balance in USD
        """
        user_brokers = self.user_brokers.get(user_id, {})
        
        if broker_type:
            broker = user_brokers.get(broker_type)
            return broker.get_account_balance() if broker else 0.0
        
        # Total across all user brokers
        total = 0.0
        for broker in user_brokers.values():
            if broker.connected:
                total += broker.get_account_balance()
        return total
    
    def get_all_balances(self) -> Dict:
        """
        Get balances for all accounts.
        
        Returns:
            dict with structure: {
                'master': {broker_type: balance, ...},
                'users': {user_id: {broker_type: balance, ...}, ...}
            }
        """
        result = {
            'master': {},
            'users': {}
        }
        
        # Master balances
        for broker_type, broker in self.master_brokers.items():
            if broker.connected:
                result['master'][broker_type.value] = broker.get_account_balance()
        
        # User balances
        for user_id, user_brokers in self.user_brokers.items():
            result['users'][user_id] = {}
            for broker_type, broker in user_brokers.items():
                if broker.connected:
                    result['users'][user_id][broker_type.value] = broker.get_account_balance()
        
        return result
    
    def get_status_report(self) -> str:
        """
        Generate a status report showing all accounts and balances.
        
        Returns:
            Formatted status report string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("NIJA MULTI-ACCOUNT STATUS REPORT")
        lines.append("=" * 70)
        
        # Master account
        lines.append("\n🔷 MASTER ACCOUNT (Nija System)")
        lines.append("-" * 70)
        if self.master_brokers:
            master_total = 0.0
            for broker_type, broker in self.master_brokers.items():
                if broker.connected:
                    balance = broker.get_account_balance()
                    master_total += balance
                    lines.append(f"   {broker_type.value.upper()}: ${balance:,.2f}")
                else:
                    lines.append(f"   {broker_type.value.upper()}: Not connected")
            lines.append(f"   TOTAL MASTER: ${master_total:,.2f}")
        else:
            lines.append("   No master brokers configured")
        
        # User accounts
        lines.append("\n🔷 USER ACCOUNTS")
        lines.append("-" * 70)
        if self.user_brokers:
            for user_id, user_brokers in self.user_brokers.items():
                lines.append(f"\n   User: {user_id}")
                user_total = 0.0
                for broker_type, broker in user_brokers.items():
                    if broker.connected:
                        balance = broker.get_account_balance()
                        user_total += balance
                        lines.append(f"      {broker_type.value.upper()}: ${balance:,.2f}")
                    else:
                        lines.append(f"      {broker_type.value.upper()}: Not connected")
                lines.append(f"      TOTAL USER: ${user_total:,.2f}")
        else:
            lines.append("   No user brokers configured")
        
        lines.append("\n" + "=" * 70)
        
        return "\n".join(lines)


# Global instance
multi_account_broker_manager = MultiAccountBrokerManager()
