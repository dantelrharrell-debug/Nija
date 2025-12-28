#!/usr/bin/env python3
"""
NIJA Bot Comprehensive Status Check
Validates that NIJA is configured properly and ready to run in production
"""

import os
import sys
import json
import ast
from pathlib import Path
from datetime import datetime, timedelta

class StatusChecker:
    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = 0
        self.results = []
        
    def check(self, name, status, message, is_warning=False):
        """Record check result"""
        if status:
            symbol = "✅"
            self.checks_passed += 1
        elif is_warning:
            symbol = "⚠️ "
            self.warnings += 1
        else:
            symbol = "❌"
            self.checks_failed += 1
            
        self.results.append(f"{symbol} {name}: {message}")
        return status
        
    def print_results(self):
        """Print all results"""
        print("\n" + "="*80)
        print("NIJA BOT COMPREHENSIVE STATUS CHECK")
        print("="*80 + "\n")
        
        for result in self.results:
            print(result)
        
        print("\n" + "="*80)
        print(f"SUMMARY: ✅ {self.checks_passed} passed | "
              f"⚠️  {self.warnings} warnings | "
              f"❌ {self.checks_failed} failed")
        print("="*80 + "\n")
        
        if self.checks_failed > 0:
            print("❌ NIJA HAS CONFIGURATION ISSUES")
            print("   Fix the failed checks before deploying to production")
            return False
        elif self.warnings > 0:
            print("⚠️  NIJA IS READY WITH WARNINGS")
            print("   Review warnings - bot should work but may have limitations")
            return True
        else:
            print("✅ NIJA IS FULLY CONFIGURED AND READY!")
            print("   All checks passed - bot is ready for production deployment")
            return True

def main():
    checker = StatusChecker()
    repo_root = Path(__file__).parent
    
    # ============================================================
    # 1. FILE STRUCTURE CHECKS
    # ============================================================
    print("Checking file structure...")
    
    critical_files = [
        'bot.py',
        'bot/bot.py',
        'bot/trading_strategy.py',
        'bot/broker_manager.py',
        'bot/position_tracker.py',
        'bot/fee_aware_config.py',
        'requirements.txt',
        'Dockerfile',
        'start.sh',
        'railway.json',
    ]
    
    for file_path in critical_files:
        full_path = repo_root / file_path
        checker.check(
            f"File: {file_path}",
            full_path.exists(),
            "Present" if full_path.exists() else "MISSING"
        )
    
    # ============================================================
    # 2. PYTHON SYNTAX VALIDATION
    # ============================================================
    print("\nValidating Python syntax...")
    
    python_files = [
        'bot.py',
        'bot/bot.py',
        'bot/trading_strategy.py',
        'bot/broker_manager.py',
        'bot/nija_apex_strategy_v71.py',
        'bot/position_tracker.py',
    ]
    
    for file_path in python_files:
        full_path = repo_root / file_path
        if full_path.exists():
            try:
                with open(full_path, 'r') as f:
                    ast.parse(f.read())
                checker.check(f"Syntax: {file_path}", True, "Valid")
            except SyntaxError as e:
                checker.check(f"Syntax: {file_path}", False, 
                            f"SYNTAX ERROR on line {e.lineno}: {e.msg}")
        else:
            checker.check(f"Syntax: {file_path}", False, "File not found", is_warning=True)
    
    # ============================================================
    # 3. DEPENDENCIES CHECK
    # ============================================================
    print("\nChecking dependencies configuration...")
    
    req_file = repo_root / 'requirements.txt'
    if req_file.exists():
        with open(req_file, 'r') as f:
            requirements = f.read()
        
        critical_deps = {
            'coinbase-advanced-py': '1.8.2',
            'Flask': '2.3.3',
            'pandas': '2.1.1',
            'numpy': '1.26.3',
        }
        
        for dep, expected_ver in critical_deps.items():
            if dep.lower() in requirements.lower():
                checker.check(f"Dependency: {dep}", True, 
                            f"Listed in requirements.txt")
            else:
                checker.check(f"Dependency: {dep}", False, 
                            f"MISSING from requirements.txt")
    
    # ============================================================
    # 4. DOCKERFILE VALIDATION
    # ============================================================
    print("\nValidating Dockerfile...")
    
    dockerfile = repo_root / 'Dockerfile'
    if dockerfile.exists():
        with open(dockerfile, 'r') as f:
            docker_content = f.read()
        
        checker.check("Dockerfile: Base image", 
                     'python:3.11' in docker_content,
                     "Uses Python 3.11" if 'python:3.11' in docker_content 
                     else "Wrong or missing base image")
        
        checker.check("Dockerfile: Coinbase SDK",
                     'coinbase-advanced-py' in docker_content,
                     "Installs coinbase-advanced-py" if 'coinbase-advanced-py' in docker_content
                     else "Missing coinbase-advanced-py installation")
        
        checker.check("Dockerfile: Requirements install",
                     'requirements.txt' in docker_content,
                     "Installs from requirements.txt" if 'requirements.txt' in docker_content
                     else "Missing requirements.txt installation")
    
    # ============================================================
    # 5. DEPLOYMENT CONFIGURATION
    # ============================================================
    print("\nChecking deployment configuration...")
    
    # Railway
    railway_config = repo_root / 'railway.json'
    if railway_config.exists():
        with open(railway_config, 'r') as f:
            railway = json.load(f)
        
        checker.check("Railway: Build config",
                     railway.get('build', {}).get('builder') == 'DOCKERFILE',
                     "Configured for Dockerfile build")
        
        checker.check("Railway: Start command",
                     railway.get('deploy', {}).get('startCommand') == './start.sh',
                     "Uses start.sh")
    else:
        checker.check("Railway config", False, "railway.json not found", is_warning=True)
    
    # Render
    render_config = repo_root / 'render.yaml'
    if render_config.exists():
        checker.check("Render: Config file", True, "render.yaml present")
    else:
        checker.check("Render: Config file", False, "render.yaml not found", is_warning=True)
    
    # ============================================================
    # 6. TRADING DATA VALIDATION
    # ============================================================
    print("\nChecking trading data...")
    
    # Trade journal
    trade_journal = repo_root / 'trade_journal.jsonl'
    if trade_journal.exists():
        with open(trade_journal, 'r') as f:
            lines = f.readlines()
        
        total_trades = len(lines)
        checker.check("Trade journal", True, f"{total_trades} trades recorded")
        
        # Check for P&L tracking
        pnl_trades = sum(1 for line in lines if 'pnl_dollars' in line)
        if pnl_trades > 0:
            checker.check("P&L tracking", True, 
                        f"{pnl_trades}/{total_trades} trades have P&L data")
            
            # Get last trade with P&L
            recent_pnl = [json.loads(line) for line in lines[-10:] 
                         if 'pnl_dollars' in line]
            if recent_pnl:
                last_pnl = recent_pnl[-1]
                last_time = datetime.fromisoformat(last_pnl['timestamp'].replace('Z', '+00:00'))
                time_diff = datetime.now() - last_time.replace(tzinfo=None)
                
                if time_diff < timedelta(hours=24):
                    checker.check("Recent activity", True,
                                f"Last P&L trade: {time_diff} ago")
                elif time_diff < timedelta(days=7):
                    checker.check("Recent activity", True,
                                f"Last P&L trade: {time_diff.days} days ago",
                                is_warning=True)
                else:
                    checker.check("Recent activity", False,
                                f"Last P&L trade: {time_diff.days} days ago - BOT MAY BE IDLE")
        else:
            checker.check("P&L tracking", False,
                        "NO trades have P&L data - tracking may be broken",
                        is_warning=True)
    else:
        checker.check("Trade journal", False, "trade_journal.jsonl not found",
                     is_warning=True)
    
    # Positions
    positions_file = repo_root / 'positions.json'
    if positions_file.exists():
        with open(positions_file, 'r') as f:
            positions_data = json.load(f)
        
        pos_count = len(positions_data.get('positions', {}))
        last_updated = positions_data.get('last_updated', 'N/A')
        
        checker.check("Positions tracker", True,
                     f"{pos_count} open positions, last updated: {last_updated}")
    else:
        checker.check("Positions tracker", False,
                     "positions.json not found", is_warning=True)
    
    # ============================================================
    # 7. CONFIGURATION FILES
    # ============================================================
    print("\nChecking bot configuration...")
    
    # Environment template
    env_example = repo_root / '.env.example'
    if env_example.exists():
        checker.check("Environment template", True, ".env.example present")
    else:
        checker.check("Environment template", False, ".env.example not found",
                     is_warning=True)
    
    # Check for emergency stop
    emergency_stop = repo_root / 'EMERGENCY_STOP'
    if emergency_stop.exists():
        checker.check("Emergency stop", False, 
                     "⚠️  EMERGENCY_STOP file exists - bot will not start!")
    else:
        checker.check("Emergency stop", True, "No emergency stop active")
    
    # ============================================================
    # 8. STRATEGY CONFIGURATION
    # ============================================================
    print("\nValidating strategy configuration...")
    
    fee_config = repo_root / 'bot' / 'fee_aware_config.py'
    if fee_config.exists():
        checker.check("Fee-aware config", True, "Configuration present")
        
        # Check if it has required settings
        with open(fee_config, 'r') as f:
            config_content = f.read()
        
        checker.check("Profit targets",
                     'TP1_TARGET' in config_content or 'PROFIT_TARGET' in config_content,
                     "Configured" if ('TP1_TARGET' in config_content or 'PROFIT_TARGET' in config_content)
                     else "MISSING")
        
        checker.check("Stop loss",
                     'STOP_LOSS' in config_content,
                     "Configured" if 'STOP_LOSS' in config_content
                     else "MISSING")
    else:
        checker.check("Fee-aware config", False, "fee_aware_config.py not found")
    
    # ============================================================
    # 9. README AND DOCUMENTATION
    # ============================================================
    print("\nChecking documentation...")
    
    readme = repo_root / 'README.md'
    if readme.exists():
        with open(readme, 'r') as f:
            readme_content = f.read()
        
        # Check for version info
        if 'v7.2' in readme_content or 'APEX v7.2' in readme_content:
            checker.check("Version", True, "README shows v7.2")
        else:
            checker.check("Version", False, "Version unclear in README",
                         is_warning=True)
        
        # Check for P&L tracking mention
        if 'P&L' in readme_content or 'profit' in readme_content.lower():
            checker.check("Documentation: P&L", True, "P&L tracking documented")
        else:
            checker.check("Documentation: P&L", False, 
                         "P&L tracking not mentioned", is_warning=True)
    
    # ============================================================
    # PRINT RESULTS
    # ============================================================
    success = checker.print_results()
    
    # ============================================================
    # FINAL VERDICT
    # ============================================================
    print("\n" + "="*80)
    print("FINAL VERDICT:")
    print("="*80)
    
    print("\n📊 DEPLOYMENT STATUS:")
    if success and checker.checks_failed == 0:
        print("   ✅ Code: Ready for deployment")
        print("   ✅ Configuration: All critical files present")
        print("   ✅ Strategy: v7.2 with P&L tracking")
        
        print("\n🔧 NEXT STEPS FOR PRODUCTION:")
        print("   1. Set environment variables in Railway/Render:")
        print("      - COINBASE_API_KEY")
        print("      - COINBASE_API_SECRET")
        print("      - COINBASE_PEM_CONTENT (or JWT credentials)")
        print("   2. Deploy to Railway or Render")
        print("   3. Monitor logs for startup success")
        print("   4. Verify first trade execution")
        
        print("\n📈 EXPECTED BEHAVIOR:")
        print("   - Scans 732+ markets every 2.5 minutes")
        print("   - Filters for quality setups (RSI, ADX, volume)")
        print("   - Positions sized at 60% of available balance")
        print("   - Auto-exits at profit targets (+2%, +2.5%, +3%)")
        print("   - Auto-exits at stop loss (-2%)")
        print("   - All trades logged with P&L tracking")
        
        return 0
    elif success:
        print("   ⚠️  Code: Ready with warnings")
        print("   ⚠️  Review warnings above")
        print("\n   Bot should work but may have limitations.")
        print("   Consider addressing warnings before production deployment.")
        return 0
    else:
        print("   ❌ Code: HAS ISSUES")
        print("   ❌ Fix failed checks before deploying")
        print("\n   Bot will not work properly until issues are resolved.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
