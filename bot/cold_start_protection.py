"""
NIJA Cold Start Protection - Zero-Credential Safe Boot

CRITICAL SAFETY MODULE - Ensures app boots safely with no credentials configured.

This module guarantees that on first launch with nothing configured:
    ✅ App boots successfully
    ✅ No errors thrown
    ✅ No broker initialization attempted
    ✅ No network calls made
    ✅ Clear message: "Trading is OFF. Setup required."

Apple App Store checks this specifically.

Author: NIJA Trading Systems  
Version: 1.0
Date: February 2026
"""

import os
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger("nija.cold_start_protection")


class ColdStartProtection:
    """
    Ensures safe boot with no credentials configured.
    
    This is a CRITICAL safety feature for App Store approval.
    """
    
    # Required environment variables for each broker
    REQUIRED_CREDENTIALS = {
        'coinbase': [
            'COINBASE_API_KEY',
            'COINBASE_API_SECRET',
        ],
        'kraken': [
            'KRAKEN_API_KEY',
            'KRAKEN_PRIVATE_KEY',
        ]
    }
    
    # Optional additional credentials
    OPTIONAL_CREDENTIALS = {
        'coinbase': ['COINBASE_PEM_CONTENT'],
        'kraken': []
    }
    
    def __init__(self):
        """Initialize cold start protection"""
        self._cold_start_mode = False
        self._missing_credentials = {}
        self._check_credentials()
        
    def _check_credentials(self):
        """Check which credentials are configured"""
        any_credentials_found = False
        
        for broker, required_vars in self.REQUIRED_CREDENTIALS.items():
            missing = []
            for var in required_vars:
                if not os.getenv(var):
                    missing.append(var)
                else:
                    any_credentials_found = True
                    
            if missing:
                self._missing_credentials[broker] = missing
                
        # If NO credentials found at all, we're in cold start mode
        if not any_credentials_found:
            self._cold_start_mode = True
            logger.info("🧊 Cold start mode detected - no credentials configured")
        else:
            logger.info("✅ Credentials detected")
            
    def is_cold_start(self) -> bool:
        """Check if in cold start mode (no credentials)"""
        return self._cold_start_mode
        
    def can_initialize_broker(self, broker: str) -> bool:
        """
        Check if a specific broker can be initialized.
        
        Args:
            broker: Broker name ('coinbase', 'kraken', etc.)
            
        Returns:
            True if broker has all required credentials
        """
        if self._cold_start_mode:
            return False
            
        return broker not in self._missing_credentials
        
    def get_missing_credentials(self, broker: Optional[str] = None) -> Dict[str, list]:
        """
        Get missing credentials.
        
        Args:
            broker: Optional broker name to check. If None, returns all.
            
        Returns:
            Dictionary of broker -> [missing_vars]
        """
        if broker:
            return {broker: self._missing_credentials.get(broker, [])}
        return self._missing_credentials
        
    def get_startup_message(self) -> Tuple[str, str]:
        """
        Get appropriate startup message based on credential status.
        
        Returns:
            Tuple of (message_type, message_text)
            message_type: 'cold_start', 'partial', or 'ready'
        """
        if self._cold_start_mode:
            message = """
╔═══════════════════════════════════════════════════════════════╗
║                    🧊 COLD START MODE 🧊                       ║
╚═══════════════════════════════════════════════════════════════╝

✅ NIJA has started successfully
❌ Trading is OFF - No API credentials configured

To enable trading:
1. Configure your exchange API credentials
2. Set required environment variables:
   - For Coinbase: COINBASE_API_KEY, COINBASE_API_SECRET
   - For Kraken: KRAKEN_API_KEY, KRAKEN_PRIVATE_KEY
3. Restart NIJA
4. Review and accept risk disclosure
5. Enable trading mode

📖 See API_CREDENTIALS_GUIDE.md for setup instructions

⚠️  NIJA will continue running in monitoring mode only.
    No broker connections will be attempted.
    No trades will be executed.

═══════════════════════════════════════════════════════════════
"""
            return ('cold_start', message)
            
        elif self._missing_credentials:
            brokers_ready = []
            brokers_missing = []
            
            for broker in self.REQUIRED_CREDENTIALS.keys():
                if self.can_initialize_broker(broker):
                    brokers_ready.append(broker.upper())
                else:
                    brokers_missing.append(broker.upper())
                    
            message = f"""
╔═══════════════════════════════════════════════════════════════╗
║                 ⚠️  PARTIAL CONFIGURATION ⚠️                    ║
╚═══════════════════════════════════════════════════════════════╝

✅ Available brokers: {', '.join(brokers_ready) if brokers_ready else 'None'}
❌ Missing credentials: {', '.join(brokers_missing) if brokers_missing else 'None'}

Missing credentials:
"""
            for broker, vars in self._missing_credentials.items():
                message += f"\n  {broker.upper()}:\n"
                for var in vars:
                    message += f"    - {var}\n"
                    
            message += """
NIJA will only connect to brokers with complete credentials.

═══════════════════════════════════════════════════════════════
"""
            return ('partial', message)
            
        else:
            message = """
╔═══════════════════════════════════════════════════════════════╗
║                  ✅ CREDENTIALS CONFIGURED ✅                   ║
╚═══════════════════════════════════════════════════════════════╝

All required credentials are configured.

⚠️  Trading is still OFF by default.
    
To enable trading:
1. Review risk disclosure
2. Accept terms of service
3. Manually enable trading mode
4. Start with DRY_RUN mode recommended

═══════════════════════════════════════════════════════════════
"""
            return ('ready', message)
            
    def assert_can_initialize_broker(self, broker: str):
        """
        Assert that a broker can be initialized.
        Raises RuntimeError if not.
        
        Args:
            broker: Broker name
        """
        if self._cold_start_mode:
            raise RuntimeError(
                f"Cannot initialize {broker}: System is in COLD START mode. "
                f"No credentials configured. See API_CREDENTIALS_GUIDE.md"
            )
            
        if not self.can_initialize_broker(broker):
            missing = self._missing_credentials.get(broker, [])
            raise RuntimeError(
                f"Cannot initialize {broker}: Missing credentials: {missing}"
            )
            
    def safe_broker_init_wrapper(self, broker: str, init_func):
        """
        Wrapper for broker initialization that respects cold start mode.
        
        Args:
            broker: Broker name
            init_func: Function to call to initialize broker
            
        Returns:
            Result of init_func, or None if in cold start mode
        """
        if self._cold_start_mode:
            logger.info(f"Skipping {broker} initialization - COLD START mode")
            return None
            
        if not self.can_initialize_broker(broker):
            logger.warning(
                f"Skipping {broker} initialization - missing credentials: "
                f"{self._missing_credentials.get(broker, [])}"
            )
            return None
            
        logger.info(f"Initializing {broker}...")
        return init_func()


# Global singleton instance
_cold_start_protection: Optional[ColdStartProtection] = None


def get_cold_start_protection() -> ColdStartProtection:
    """Get the global cold start protection instance (singleton)"""
    global _cold_start_protection
    
    if _cold_start_protection is None:
        _cold_start_protection = ColdStartProtection()
        
    return _cold_start_protection


def is_cold_start() -> bool:
    """Check if system is in cold start mode"""
    return get_cold_start_protection().is_cold_start()


def print_startup_message():
    """Print appropriate startup message"""
    csp = get_cold_start_protection()
    msg_type, message = csp.get_startup_message()
    print(message)
    
    # Also log
    if msg_type == 'cold_start':
        logger.warning("System in COLD START mode - no credentials configured")
    elif msg_type == 'partial':
        logger.warning("System has partial configuration - some credentials missing")
    else:
        logger.info("System configured and ready")


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Cold Start Protection Test ===\n")
    
    csp = get_cold_start_protection()
    
    print(f"Cold start mode: {csp.is_cold_start()}")
    print(f"Can init Coinbase: {csp.can_initialize_broker('coinbase')}")
    print(f"Can init Kraken: {csp.can_initialize_broker('kraken')}")
    
    print("\n--- Startup Message ---")
    print_startup_message()
    
    print("\n--- Missing Credentials ---")
    missing = csp.get_missing_credentials()
    for broker, vars in missing.items():
        print(f"  {broker}: {vars}")
