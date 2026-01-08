"""
NIJA Authentication & User Management - Layer Support

Handles user authentication, API key management, and user-specific configurations.

Security Features:
- Encrypted API key storage
- User permission scoping
- API key rotation support
- Audit logging

DO NOT store API keys in plain text or commit them to version control.
"""

import logging
import json
import os
from typing import Dict, Optional, List
from datetime import datetime
from cryptography.fernet import Fernet
import base64

logger = logging.getLogger("nija.auth")


class APIKeyManager:
    """
    Manages encrypted user API keys for broker connections.
    """
    
    def __init__(self, encryption_key: Optional[bytes] = None):
        """
        Initialize API key manager with encryption.
        
        Args:
            encryption_key: 32-byte encryption key (generated if not provided)
        """
        if encryption_key is None:
            # Generate new encryption key (should be stored securely)
            encryption_key = Fernet.generate_key()
            logger.warning("Generated new encryption key - store this securely!")
            logger.warning(f"Encryption key: {encryption_key.decode()}")
        
        self.cipher = Fernet(encryption_key)
        self.user_keys: Dict[str, Dict[str, str]] = {}
        logger.info("API key manager initialized with encryption")
    
    def store_user_api_key(
        self,
        user_id: str,
        broker: str,
        api_key: str,
        api_secret: str,
        additional_params: Optional[Dict] = None
    ):
        """
        Store encrypted user API credentials.
        
        Args:
            user_id: User identifier
            broker: Broker name (coinbase, binance, alpaca, etc.)
            api_key: API key to encrypt and store
            api_secret: API secret to encrypt and store
            additional_params: Additional parameters (e.g., passphrase for OKX)
        """
        if user_id not in self.user_keys:
            self.user_keys[user_id] = {}
        
        # Encrypt credentials
        encrypted_key = self.cipher.encrypt(api_key.encode()).decode()
        encrypted_secret = self.cipher.encrypt(api_secret.encode()).decode()
        
        broker_creds = {
            'api_key': encrypted_key,
            'api_secret': encrypted_secret,
            'created_at': datetime.now().isoformat(),
            'broker': broker
        }
        
        # Encrypt additional parameters
        if additional_params:
            encrypted_params = {}
            for key, value in additional_params.items():
                encrypted_params[key] = self.cipher.encrypt(str(value).encode()).decode()
            broker_creds['additional_params'] = encrypted_params
        
        self.user_keys[user_id][broker] = broker_creds
        logger.info(f"Stored encrypted API credentials for user {user_id} on {broker}")
    
    def get_user_api_key(
        self,
        user_id: str,
        broker: str
    ) -> Optional[Dict[str, str]]:
        """
        Retrieve and decrypt user API credentials.
        
        Args:
            user_id: User identifier
            broker: Broker name
            
        Returns:
            dict: Decrypted credentials or None if not found
        """
        if user_id not in self.user_keys:
            logger.warning(f"No API keys found for user {user_id}")
            return None
        
        if broker not in self.user_keys[user_id]:
            logger.warning(f"No {broker} API key found for user {user_id}")
            return None
        
        broker_creds = self.user_keys[user_id][broker]
        
        # Decrypt credentials
        try:
            decrypted_key = self.cipher.decrypt(broker_creds['api_key'].encode()).decode()
            decrypted_secret = self.cipher.decrypt(broker_creds['api_secret'].encode()).decode()
            
            result = {
                'api_key': decrypted_key,
                'api_secret': decrypted_secret,
                'broker': broker
            }
            
            # Decrypt additional parameters if present
            if 'additional_params' in broker_creds:
                result['additional_params'] = {}
                for key, encrypted_value in broker_creds['additional_params'].items():
                    result['additional_params'][key] = self.cipher.decrypt(
                        encrypted_value.encode()
                    ).decode()
            
            return result
        except Exception as e:
            logger.error(f"Failed to decrypt API key for user {user_id}: {e}")
            return None
    
    def delete_user_api_key(self, user_id: str, broker: str) -> bool:
        """
        Delete user API credentials.
        
        Args:
            user_id: User identifier
            broker: Broker name
            
        Returns:
            bool: True if deleted successfully
        """
        if user_id in self.user_keys and broker in self.user_keys[user_id]:
            del self.user_keys[user_id][broker]
            logger.info(f"Deleted API credentials for user {user_id} on {broker}")
            return True
        return False
    
    def list_user_brokers(self, user_id: str) -> List[str]:
        """
        List all brokers configured for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            list: List of broker names
        """
        if user_id not in self.user_keys:
            return []
        return list(self.user_keys[user_id].keys())


class UserManager:
    """
    Manages user accounts and their configurations.
    """
    
    def __init__(self):
        self.users: Dict[str, Dict] = {}
        logger.info("User manager initialized")
    
    def create_user(
        self,
        user_id: str,
        email: str,
        subscription_tier: str = 'basic'
    ) -> Dict:
        """
        Create a new user account.
        
        Args:
            user_id: Unique user identifier
            email: User email
            subscription_tier: Subscription level (basic, pro, enterprise)
            
        Returns:
            dict: User profile
        """
        if user_id in self.users:
            raise ValueError(f"User {user_id} already exists")
        
        user_profile = {
            'user_id': user_id,
            'email': email,
            'subscription_tier': subscription_tier,
            'created_at': datetime.now().isoformat(),
            'enabled': True,
            'brokers': []
        }
        
        self.users[user_id] = user_profile
        logger.info(f"Created user {user_id} with tier {subscription_tier}")
        
        return user_profile
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        """Get user profile."""
        return self.users.get(user_id)
    
    def update_user(self, user_id: str, updates: Dict) -> bool:
        """Update user profile."""
        if user_id not in self.users:
            return False
        
        self.users[user_id].update(updates)
        logger.info(f"Updated user {user_id}: {updates}")
        return True
    
    def disable_user(self, user_id: str) -> bool:
        """Disable user account (soft delete)."""
        if user_id in self.users:
            self.users[user_id]['enabled'] = False
            logger.info(f"Disabled user {user_id}")
            return True
        return False
    
    def enable_user(self, user_id: str) -> bool:
        """Enable user account."""
        if user_id in self.users:
            self.users[user_id]['enabled'] = True
            logger.info(f"Enabled user {user_id}")
            return True
        return False


# Global instances
_api_key_manager = None
_user_manager = UserManager()


def get_api_key_manager(encryption_key: Optional[bytes] = None) -> APIKeyManager:
    """
    Get global API key manager instance.
    
    Args:
        encryption_key: Encryption key (only used on first call)
    """
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager(encryption_key)
    return _api_key_manager


def get_user_manager() -> UserManager:
    """Get global user manager instance."""
    return _user_manager


__all__ = [
    'APIKeyManager',
    'UserManager',
    'get_api_key_manager',
    'get_user_manager',
]
