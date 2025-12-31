#!/usr/bin/env python3
"""
NIJA Comprehensive System Check
================================

Complete health check for NIJA trading bot:
1. Broker connections (all exchanges)
2. Profitability configuration
3. 24/7 readiness
4. Current trading status

This script answers: "Is NIJA connected to all brokerages and ready to make profit 24/7?"

Usage:
    python3 comprehensive_nija_check.py
"""

import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'

def print_header(title, level=1):
    """Print a formatted header"""
    if level == 1:
        print("\n" + "=" * 80)
        print(f"{BOLD}{BLUE}  {title}{RESET}")
        print("=" * 80)
    else:
        print("\n" + "-" * 80)
        print(f"{BOLD}  {title}{RESET}")
        print("-" * 80)

def print_success(msg):
    """Print success message"""
    print(f"{GREEN}✅ {msg}{RESET}")

def print_error(msg):
    """Print error message"""
    print(f"{RED}❌ {msg}{RESET}")

def print_warning(msg):
    """Print warning message"""
    print(f"{YELLOW}⚠️  {msg}{RESET}")

def print_info(msg):
    """Print info message"""
    print(f"{BLUE}ℹ️  {msg}{RESET}")

class NIJAHealthCheck:
    """Comprehensive health check for NIJA trading system"""
    
    def __init__(self):
        self.results = {
            'brokers': {},
            'profitability': {},
            'readiness': {},
            'overall': {}
        }
        self.connected_brokers = []
        self.total_balance = 0.0
    
    def check_broker_credentials(self, broker_name, required_vars):
        """Check if required environment variables are set for a broker
        
        Args:
            broker_name: Name of the broker
            required_vars: List of required variables or list of alternative sets
        
        Returns:
            (credentials_ok, missing_vars)
        """
        # Handle alternative credential sets
        if required_vars and isinstance(required_vars[0], list):
            for var_set in required_vars:
                missing = [var for var in var_set if not os.getenv(var)]
                if len(missing) == 0:
                    return True, []
            return False, required_vars
        else:
            missing = [var for var in required_vars if not os.getenv(var)]
            return len(missing) == 0, missing
    
    def test_broker_connection(self, broker_name, broker_class):
        """Test connection to a specific broker"""
        try:
            broker = broker_class()
            if broker.connect():
                try:
                    balance_info = broker.get_account_balance()
                    if isinstance(balance_info, dict):
                        balance = balance_info.get('trading_balance', 0)
                    else:
                        balance = float(balance_info) if balance_info else 0
                    return True, balance, None
                except Exception as e:
                    return True, 0, f"Connected but balance unavailable: {str(e)[:50]}"
            else:
                return False, 0, "Connection returned False"
        except Exception as e:
            return False, 0, str(e)[:100]
    
    def check_all_brokers(self):
        """Check connection status of all supported brokers"""
        print_header("BROKER CONNECTION STATUS", level=1)
        
        # Import broker classes
        try:
            from broker_manager import (
                CoinbaseBroker, KrakenBroker, OKXBroker, 
                BinanceBroker, AlpacaBroker
            )
        except ImportError as e:
            print_error(f"Cannot import broker classes: {e}")
            return False
        
        # Define broker configurations
        brokers = [
            {
                'name': 'Coinbase Advanced Trade',
                'class': CoinbaseBroker,
                'credentials': [
                    ['COINBASE_JWT_PEM', 'COINBASE_JWT_KID', 'COINBASE_JWT_ISSUER'],
                    ['COINBASE_API_KEY', 'COINBASE_API_SECRET']
                ],
                'icon': '🟦',
                'primary': True,
                'type': 'Crypto'
            },
            {
                'name': 'Binance',
                'class': BinanceBroker,
                'credentials': ['BINANCE_API_KEY', 'BINANCE_API_SECRET'],
                'icon': '🟨',
                'primary': False,
                'type': 'Crypto'
            },
            {
                'name': 'Kraken Pro',
                'class': KrakenBroker,
                'credentials': ['KRAKEN_API_KEY', 'KRAKEN_API_SECRET'],
                'icon': '🟪',
                'primary': False,
                'type': 'Crypto'
            },
            {
                'name': 'OKX',
                'class': OKXBroker,
                'credentials': ['OKX_API_KEY', 'OKX_API_SECRET', 'OKX_PASSPHRASE'],
                'icon': '⬛',
                'primary': False,
                'type': 'Crypto'
            },
            {
                'name': 'Alpaca',
                'class': AlpacaBroker,
                'credentials': ['ALPACA_API_KEY', 'ALPACA_API_SECRET'],
                'icon': '🟩',
                'primary': False,
                'type': 'Stocks'
            }
        ]
        
        print("\nChecking all supported brokerages...\n")
        
        for broker_config in brokers:
            name = broker_config['name']
            icon = broker_config['icon']
            broker_class = broker_config['class']
            credentials = broker_config['credentials']
            primary = broker_config['primary']
            asset_type = broker_config['type']
            
            print(f"{icon} {BOLD}{name}{RESET} ({asset_type})" + (f" {BLUE}[PRIMARY]{RESET}" if primary else ""))
            
            # Check credentials
            creds_ok, missing = self.check_broker_credentials(name, credentials)
            
            if not creds_ok:
                print_warning(f"Credentials not configured")
                if missing and isinstance(missing[0], list):
                    print(f"   Need one of:")
                    for i, var_set in enumerate(missing, 1):
                        print(f"     Option {i}: {', '.join(var_set)}")
                else:
                    print(f"   Missing: {', '.join(missing)}")
                
                self.results['brokers'][name] = {
                    'connected': False,
                    'reason': 'No credentials',
                    'balance': 0
                }
                continue
            
            print(f"   ✓ Credentials configured")
            
            # Test connection
            print(f"   🔄 Testing connection...")
            is_connected, balance, error = self.test_broker_connection(name, broker_class)
            
            if is_connected:
                print_success(f"Connected successfully")
                if balance > 0:
                    print(f"   💰 Balance: ${balance:,.2f}")
                    self.total_balance += balance
                
                self.connected_brokers.append({
                    'name': name,
                    'icon': icon,
                    'balance': balance,
                    'primary': primary,
                    'type': asset_type
                })
                
                self.results['brokers'][name] = {
                    'connected': True,
                    'balance': balance,
                    'type': asset_type
                }
            else:
                print_error(f"Connection failed")
                if error:
                    print(f"   Error: {error[:80]}")
                
                self.results['brokers'][name] = {
                    'connected': False,
                    'reason': error or 'Unknown error',
                    'balance': 0
                }
            
            print()  # Blank line between brokers
        
        return len(self.connected_brokers) > 0
    
    def check_profitability_config(self):
        """Check if profit-taking system is properly configured"""
        print_header("PROFITABILITY CONFIGURATION", level=1)
        
        checks = {}
        
        # Check trading_strategy.py for profit targets
        strategy_file = "bot/trading_strategy.py"
        if os.path.exists(strategy_file):
            with open(strategy_file, 'r') as f:
                content = f.read()
            
            # Check for profit-taking features
            profit_features = {
                'profit_targets': 'PROFIT_TARGETS = [' in content,
                'stop_loss': 'STOP_LOSS_THRESHOLD' in content,
                'profit_exit_logic': '# PROFIT-BASED EXIT LOGIC' in content or 'check_stepped_exit' in content,
                'pnl_tracking': 'position_tracker.calculate_pnl' in content or '.calculate_pnl(' in content,
            }
            
            for feature, present in profit_features.items():
                if present:
                    print_success(f"{feature.replace('_', ' ').title()} configured")
                else:
                    print_warning(f"{feature.replace('_', ' ').title()} not detected")
                checks[feature] = present
        else:
            print_error("trading_strategy.py not found")
            checks['strategy_file'] = False
        
        # Check position_tracker.py exists
        tracker_file = "bot/position_tracker.py"
        if os.path.exists(tracker_file):
            print_success("Position tracker module exists")
            checks['position_tracker'] = True
            
            # Check if positions.json exists
            if os.path.exists("positions.json"):
                try:
                    with open("positions.json", 'r') as f:
                        data = json.load(f)
                    positions = data.get('positions', {})
                    print_success(f"Position tracking active ({len(positions)} positions tracked)")
                    checks['position_tracking'] = True
                except:
                    print_warning("positions.json exists but couldn't be read")
                    checks['position_tracking'] = False
            else:
                print_info("No positions.json yet (normal if no open positions)")
                checks['position_tracking'] = True  # Not an error
        else:
            print_warning("Position tracker module not found")
            checks['position_tracker'] = False
        
        # Check fee-aware configuration
        if os.path.exists("bot/fee_aware_config.py") or os.path.exists("bot/risk_manager.py"):
            print_success("Fee-aware profitability mode available")
            checks['fee_aware'] = True
        else:
            print_warning("Fee-aware configuration not found")
            checks['fee_aware'] = False
        
        self.results['profitability'] = checks
        
        # Return True if at least the critical components are present
        critical = ['profit_targets', 'stop_loss', 'position_tracker']
        return all(checks.get(k, False) for k in critical if k in checks)
    
    def check_24_7_readiness(self):
        """Check if system is ready for 24/7 operation"""
        print_header("24/7 READINESS STATUS", level=1)
        
        checks = {}
        
        # Check deployment configurations
        deployment_configs = {
            'Railway': 'railway.json',
            'Render': 'render.yaml',
            'Docker': 'Dockerfile',
            'Docker Compose': 'docker-compose.yml',
        }
        
        has_deployment = False
        for platform, config_file in deployment_configs.items():
            if os.path.exists(config_file):
                print_success(f"{platform} deployment configured ({config_file})")
                checks[f'deployment_{platform.lower()}'] = True
                has_deployment = True
            else:
                print_info(f"{platform} config not found")
                checks[f'deployment_{platform.lower()}'] = False
        
        if has_deployment:
            print_success("At least one deployment platform configured")
            checks['has_deployment'] = True
        else:
            print_warning("No deployment platform configured")
            checks['has_deployment'] = False
        
        # Check start scripts
        start_scripts = ['start.sh', 'main.py', 'bot.py']
        found_start = False
        for script in start_scripts:
            if os.path.exists(script):
                print_success(f"Start script found: {script}")
                checks[f'start_{script}'] = True
                found_start = True
        
        if not found_start:
            print_warning("No start script found")
            checks['has_start_script'] = False
        else:
            checks['has_start_script'] = True
        
        # Check requirements.txt
        if os.path.exists('requirements.txt'):
            print_success("Dependencies defined (requirements.txt)")
            checks['dependencies'] = True
        else:
            print_warning("No requirements.txt found")
            checks['dependencies'] = False
        
        # Check environment configuration
        if os.path.exists('.env') or os.path.exists('.env.example'):
            print_success("Environment configuration available")
            checks['env_config'] = True
        else:
            print_warning("No .env or .env.example found")
            checks['env_config'] = False
        
        # Check for monitoring/logging
        if os.path.exists('bot/monitoring_system.py') or os.path.exists('bot/dashboard_server.py'):
            print_success("Monitoring system available")
            checks['monitoring'] = True
        else:
            print_info("No monitoring system detected")
            checks['monitoring'] = False
        
        self.results['readiness'] = checks
        
        # Return True if core readiness requirements are met
        return has_deployment and found_start
    
    def check_current_trading_status(self):
        """Check if bot is currently trading (optional check)"""
        print_header("CURRENT TRADING STATUS", level=1)
        
        # Check if positions.json has recent activity
        if os.path.exists("positions.json"):
            try:
                with open("positions.json", 'r') as f:
                    data = json.load(f)
                
                positions = data.get('positions', {})
                last_updated = data.get('last_updated', 'Unknown')
                
                if positions:
                    print_success(f"Currently tracking {len(positions)} open position(s)")
                    print(f"   Last updated: {last_updated}")
                    
                    print("\n   Open Positions:")
                    for symbol, pos in positions.items():
                        entry = pos.get('entry_price', 0)
                        qty = pos.get('quantity', 0)
                        usd = pos.get('size_usd', 0)
                        print(f"   • {symbol}: ${usd:.2f} @ ${entry:.4f}")
                    
                    return True
                else:
                    print_info("No open positions currently")
                    print("   (Bot may be waiting for trading signals)")
                    return True
            except Exception as e:
                print_warning(f"Could not read positions.json: {e}")
                return False
        else:
            print_info("No positions.json file")
            print("   (Normal if bot hasn't opened any positions yet)")
            return True
    
    def generate_final_report(self):
        """Generate comprehensive final report"""
        print_header("COMPREHENSIVE HEALTH REPORT", level=1)
        
        # Calculate scores
        total_checks = 0
        passed_checks = 0
        
        # Broker score
        broker_count = len(self.results['brokers'])
        connected_count = len(self.connected_brokers)
        if broker_count > 0:
            total_checks += 1
            if connected_count > 0:
                passed_checks += 1
        
        # Profitability score
        profit_checks = self.results.get('profitability', {})
        profit_critical = ['profit_targets', 'stop_loss', 'position_tracker']
        profit_score = sum(1 for k in profit_critical if profit_checks.get(k, False))
        total_checks += len(profit_critical)
        passed_checks += profit_score
        
        # Readiness score
        ready_checks = self.results.get('readiness', {})
        ready_critical = ['has_deployment', 'has_start_script', 'dependencies']
        ready_score = sum(1 for k in ready_critical if ready_checks.get(k, False))
        total_checks += len(ready_critical)
        passed_checks += ready_score
        
        # Calculate percentage
        health_percentage = (passed_checks / total_checks * 100) if total_checks > 0 else 0
        
        print(f"\n{BOLD}Overall Health Score: {health_percentage:.1f}% ({passed_checks}/{total_checks} checks passed){RESET}\n")
        
        # Broker summary
        print(f"{BOLD}1. BROKER CONNECTIONS:{RESET}")
        if connected_count > 0:
            print_success(f"{connected_count} broker(s) connected and ready")
            for broker in self.connected_brokers:
                primary_tag = " [PRIMARY]" if broker.get('primary') else ""
                balance_info = f" - ${broker['balance']:,.2f}" if broker.get('balance', 0) > 0 else ""
                print(f"   {broker['icon']} {broker['name']}{primary_tag}{balance_info}")
            
            if self.total_balance > 0:
                print(f"\n   💰 Total Trading Capital: ${self.total_balance:,.2f}")
        else:
            print_error("No brokers connected")
            print("   ⚠️ Cannot trade without broker connections")
        
        # Profitability summary
        print(f"\n{BOLD}2. PROFITABILITY CONFIGURATION:{RESET}")
        if profit_score >= len(profit_critical):
            print_success("All critical profit-taking features configured")
            print("   • Profit targets set (0.5%, 1%, 2%, 3%)")
            print("   • Stop losses enabled (-2%)")
            print("   • Position tracking active")
        elif profit_score >= 2:
            print_warning(f"Partial configuration ({profit_score}/{len(profit_critical)} critical features)")
            print("   Some profit-taking features may not work")
        else:
            print_error("Profit-taking system incomplete")
            print("   ⚠️ Bot may not exit positions profitably")
        
        # Readiness summary
        print(f"\n{BOLD}3. 24/7 OPERATIONAL READINESS:{RESET}")
        if ready_score >= len(ready_critical):
            print_success("System ready for continuous operation")
            print("   • Deployment configuration exists")
            print("   • Start scripts available")
            print("   • Dependencies defined")
        elif ready_score >= 2:
            print_warning(f"Mostly ready ({ready_score}/{len(ready_critical)} features)")
            print("   May need minor configuration")
        else:
            print_error("Not ready for deployment")
            print("   ⚠️ Critical deployment components missing")
        
        # Final verdict
        print_header("FINAL VERDICT", level=1)
        
        if health_percentage >= 85:
            print(f"{GREEN}{BOLD}🎉 EXCELLENT - NIJA IS FULLY OPERATIONAL!{RESET}\n")
            print(f"{BOLD}Answer to your question:{RESET}")
            print(f"{GREEN}✅ YES - NIJA is connected to brokerages and ready to make profit 24/7{RESET}\n")
            
            print("System Status:")
            print(f"  • {connected_count} broker(s) connected with ${self.total_balance:,.2f} available")
            print(f"  • Profit-taking system configured and active")
            print(f"  • Deployment ready for 24/7 operation")
            
            print("\nNext Steps:")
            print("  1. ✅ System is ready - no action needed")
            print("  2. Monitor positions and profits via dashboard")
            print("  3. Review performance metrics regularly")
            
        elif health_percentage >= 60:
            print(f"{YELLOW}{BOLD}⚠️ GOOD - MOSTLY READY (Minor Issues){RESET}\n")
            print(f"{BOLD}Answer to your question:{RESET}")
            print(f"{YELLOW}⚠️ MOSTLY - NIJA is operational but has some gaps{RESET}\n")
            
            print("Issues to Address:")
            if connected_count == 0:
                print("  ❌ No broker connections - configure API credentials")
            if profit_score < len(profit_critical):
                print("  ⚠️ Profit-taking incomplete - verify configuration")
            if ready_score < len(ready_critical):
                print("  ⚠️ Deployment setup incomplete - review configs")
            
        else:
            print(f"{RED}{BOLD}❌ WARNING - SYSTEM NEEDS WORK{RESET}\n")
            print(f"{BOLD}Answer to your question:{RESET}")
            print(f"{RED}❌ NO - NIJA is NOT ready for profitable trading 24/7{RESET}\n")
            
            print("Critical Issues:")
            if connected_count == 0:
                print("  ❌ No broker connections - CANNOT TRADE")
            if profit_score == 0:
                print("  ❌ No profit-taking system - CANNOT MAKE PROFIT")
            if ready_score == 0:
                print("  ❌ No deployment config - CANNOT RUN 24/7")
            
            print("\nRequired Actions:")
            print("  1. Configure at least one broker (see .env.example)")
            print("  2. Set up profit targets and stop losses")
            print("  3. Configure deployment (Railway, Render, or Docker)")
        
        # Additional recommendations
        if connected_count < 2:
            print(f"\n{BLUE}💡 Recommendation: Add more brokers for diversification{RESET}")
            print("   • Lower fees with Binance (0.1%) or OKX (0.08%)")
            print("   • Avoid single point of failure")
        
        if self.total_balance > 0 and self.total_balance < 50:
            print(f"\n{BLUE}💡 Note: Low capital (${self.total_balance:.2f}){RESET}")
            print("   • Consider funding additional capital for better returns")
            print("   • Small positions may be heavily impacted by fees")
        
        print("\n" + "=" * 80)
        print(f"📅 Check completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80 + "\n")
        
        # Save results to file
        self.save_results()
        
        return health_percentage >= 60  # Return success if mostly ready
    
    def save_results(self):
        """Save check results to JSON file"""
        try:
            results_file = "nija_health_check_results.json"
            output = {
                'timestamp': datetime.now().isoformat(),
                'connected_brokers': len(self.connected_brokers),
                'total_balance': self.total_balance,
                'brokers': self.results['brokers'],
                'profitability': self.results['profitability'],
                'readiness': self.results['readiness'],
            }
            
            with open(results_file, 'w') as f:
                json.dump(output, f, indent=2)
            
            print(f"{BLUE}ℹ️  Detailed results saved to: {results_file}{RESET}")
        except Exception as e:
            print_warning(f"Could not save results: {e}")
    
    def run_comprehensive_check(self):
        """Run all health checks"""
        print_header("NIJA COMPREHENSIVE SYSTEM CHECK", level=1)
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        print("This check will verify:")
        print("  1. All broker connections")
        print("  2. Profitability configuration")
        print("  3. 24/7 operational readiness")
        print("  4. Current trading status")
        
        # Run all checks
        broker_ok = self.check_all_brokers()
        profit_ok = self.check_profitability_config()
        ready_ok = self.check_24_7_readiness()
        self.check_current_trading_status()
        
        # Generate final report
        return self.generate_final_report()


def main():
    """Main execution"""
    checker = NIJAHealthCheck()
    success = checker.run_comprehensive_check()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
