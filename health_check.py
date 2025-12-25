#!/usr/bin/env python3
"""
NIJA Automated Health Check & Validation System

Validates bot configuration, connectivity, and trading readiness.
Run this before deploying to ensure everything is configured correctly.

Author: NIJA Trading Systems
Version: 1.0
Date: December 19, 2025
"""

import sys
import os
from pathlib import Path
from typing import List, Tuple, Optional
import json
import logging

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "bot"))

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class HealthCheck:
    """Health check validation system"""
    
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
    
    def check(self, name: str, condition: bool, error_msg: str = "", warning: bool = False):
        """Run a health check"""
        if condition:
            self.passed.append(name)
            logger.info(f"✅ {name}")
            return True
        else:
            if warning:
                self.warnings.append((name, error_msg))
                logger.warning(f"⚠️  {name}: {error_msg}")
            else:
                self.failed.append((name, error_msg))
                logger.error(f"❌ {name}: {error_msg}")
            return False
    
    def summary(self) -> bool:
        """Print summary and return overall status"""
        logger.info("\n" + "="*70)
        logger.info("HEALTH CHECK SUMMARY")
        logger.info("="*70)
        logger.info(f"✅ Passed:   {len(self.passed)}")
        logger.info(f"⚠️  Warnings: {len(self.warnings)}")
        logger.info(f"❌ Failed:   {len(self.failed)}")
        logger.info("="*70)
        
        if self.failed:
            logger.error("\n❌ FAILED CHECKS:")
            for name, msg in self.failed:
                logger.error(f"  - {name}: {msg}")
        
        if self.warnings:
            logger.warning("\n⚠️  WARNINGS:")
            for name, msg in self.warnings:
                logger.warning(f"  - {name}: {msg}")
        
        return len(self.failed) == 0


def main():
    """Run all health checks"""
    logger.info("="*70)
    logger.info("🔍 NIJA BOT HEALTH CHECK & VALIDATION")
    logger.info("="*70)
    logger.info("")
    
    health = HealthCheck()
    
    # ==================== ENVIRONMENT CHECKS ====================
    logger.info("📋 Environment Configuration")
    logger.info("-"*70)
    
    # Check for .env file
    env_file = Path(".env")
    health.check(
        "Environment file exists",
        env_file.exists(),
        "Missing .env file - copy .env.example and configure"
    )
    
    # Check required environment variables
    required_vars = [
        "COINBASE_API_KEY",
        "COINBASE_API_SECRET",
        "COINBASE_PEM_CONTENT"
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        health.check(
            f"Environment variable: {var}",
            value is not None and len(value) > 0,
            f"{var} not set or empty"
        )
    
    logger.info("")
    
    # ==================== FILE STRUCTURE CHECKS ====================
    logger.info("📁 File Structure")
    logger.info("-"*70)
    
    critical_files = [
        "bot/trading_strategy.py",
        "bot/broker_integration.py",
        "bot/risk_manager.py",
        "bot/fee_aware_config.py",
        "bot/monitoring_system.py",
        "requirements.txt",
        "Dockerfile",
        "start.sh"
    ]
    
    for file_path in critical_files:
        health.check(
            f"File exists: {file_path}",
            Path(file_path).exists(),
            f"Missing critical file: {file_path}"
        )
    
    logger.info("")
    
    # ==================== PYTHON DEPENDENCIES ====================
    logger.info("📦 Python Dependencies")
    logger.info("-"*70)
    
    required_packages = [
        "coinbase",
        "flask",
        "pandas",
        "numpy",
        "requests"
    ]
    
    for package in required_packages:
        try:
            __import__(package)
            health.check(f"Package: {package}", True)
        except ImportError:
            health.check(
                f"Package: {package}",
                False,
                f"Install with: pip install {package}"
            )
    
    logger.info("")
    
    # ==================== BOT CONFIGURATION ====================
    logger.info("⚙️  Bot Configuration")
    logger.info("-"*70)
    
    try:
        # Try importing bot modules
        from fee_aware_config import MIN_BALANCE_TO_TRADE, SMALL_BALANCE_POSITION_PCT
        
        health.check(
            f"Minimum balance requirement: ${MIN_BALANCE_TO_TRADE}",
            MIN_BALANCE_TO_TRADE >= 50.0,
            f"MIN_BALANCE_TO_TRADE should be >= $50 (currently ${MIN_BALANCE_TO_TRADE})",
            warning=True
        )
        
        health.check(
            f"Position sizing configured: {SMALL_BALANCE_POSITION_PCT*100}%",
            0.5 <= SMALL_BALANCE_POSITION_PCT <= 1.0,
            f"Position size should be 50-100% for small accounts"
        )
        
    except ImportError as e:
        health.check(
            "Import fee_aware_config",
            False,
            f"Cannot import configuration: {e}"
        )
    
    logger.info("")
    
    # ==================== COINBASE CONNECTIVITY ====================
    logger.info("🔌 Coinbase API Connectivity")
    logger.info("-"*70)
    
    try:
        from broker_integration import CoinbaseAdvancedTradeBroker
        
        # Try to connect
        broker = CoinbaseAdvancedTradeBroker()
        health.check("Coinbase broker initialized", True)
        
        try:
            balance = broker.get_balance()
            health.check(
                f"Account balance retrieved: ${balance:.2f}",
                balance >= 0,
                "Could not retrieve balance"
            )
            
            health.check(
                f"Minimum balance met (${balance:.2f} >= $50)",
                balance >= 50.0,
                f"Balance too low for profitable trading: ${balance:.2f}. Need $50+",
                warning=True
            )
            
        except Exception as e:
            health.check(
                "Get account balance",
                False,
                f"API error: {str(e)}"
            )
        
        try:
            # Try to get market data
            price = broker.get_current_price("BTC-USD")
            health.check(
                f"Market data access (BTC-USD: ${price:.2f})",
                price > 0,
                "Cannot retrieve market data"
            )
        except Exception as e:
            health.check(
                "Get market data",
                False,
                f"Cannot access market data: {str(e)}"
            )
        
    except Exception as e:
        health.check(
            "Coinbase connectivity",
            False,
            f"Cannot connect to Coinbase: {str(e)}"
        )
    
    logger.info("")
    
    # ==================== FEE-AWARE MODE ====================
    logger.info("💰 Fee-Aware Profitability Mode")
    logger.info("-"*70)
    
    try:
        from risk_manager import FEE_AWARE_MODE
        
        health.check(
            "Fee-aware mode active",
            FEE_AWARE_MODE == True,
            "Fee-aware mode not enabled - profitability at risk!",
            warning=True
        )
    except:
        health.check(
            "Fee-aware mode check",
            False,
            "Cannot verify fee-aware mode status"
        )
    
    logger.info("")
    
    # ==================== DIRECTORY PERMISSIONS ====================
    logger.info("📂 Directory Permissions")
    logger.info("-"*70)
    
    data_dirs = [
        Path("/tmp/nija_monitoring"),
        Path("/usr/src/app/data") if Path("/usr/src/app").exists() else Path("./data")
    ]
    
    for dir_path in data_dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            test_file = dir_path / ".health_check_test"
            test_file.write_text("test")
            test_file.unlink()
            health.check(f"Write access: {dir_path}", True)
        except Exception as e:
            health.check(
                f"Write access: {dir_path}",
                False,
                f"Cannot write to directory: {e}",
                warning=True
            )
    
    logger.info("")
    
    # ==================== MONITORING SYSTEM ====================
    logger.info("📊 Monitoring System")
    logger.info("-"*70)
    
    try:
        from monitoring_system import monitoring
        health.check("Monitoring system available", True)
        
        # Test monitoring
        monitoring.update_balance(50.0)
        monitoring.record_api_call()
        
        health_status = monitoring.check_health()
        health.check(
            "Monitoring health check",
            health_status.get('status') is not None
        )
        
    except Exception as e:
        health.check(
            "Monitoring system",
            False,
            f"Monitoring not available: {e}",
            warning=True
        )
    
    logger.info("")
    
    # ==================== FINAL SUMMARY ====================
    all_passed = health.summary()
    
    if all_passed:
        logger.info("\n🎉 ALL CRITICAL CHECKS PASSED!")
        logger.info("✅ Bot is ready for deployment")
        if health.warnings:
            logger.info("⚠️  Review warnings above for optimization opportunities")
        return 0
    else:
        logger.error("\n🚨 HEALTH CHECK FAILED!")
        logger.error("❌ Fix the failed checks before deploying")
        logger.error("📖 See error messages above for details")
        return 1


if __name__ == "__main__":
    sys.exit(main())
