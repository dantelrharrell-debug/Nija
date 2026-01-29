#!/usr/bin/env python3
"""
Start NIJA with both autonomous trading AND TradingView webhook support
Runs both services concurrently
"""

import os
import sys
import threading
import time

def run_autonomous_bot():
    """Run the autonomous trading bot"""
    print("🤖 Starting NIJA Autonomous Trading Bot...")
    os.system('python3 bot/live_bot_script.py')

def run_webhook_service():
    """Run the TradingView webhook service"""
    print("📡 Starting NIJA TradingView Webhook Service...")
    time.sleep(2)  # Let autonomous bot initialize first
    os.system('python3 bot/tradingview_webhook.py')

if __name__ == '__main__':
    print(f"\n{'='*70}")
    print(f"🚀 NIJA DUAL-MODE TRADING SYSTEM")
    print(f"{'='*70}")
    print(f"Mode 1: Autonomous - Scans 732 markets every 2.5 minutes")
    print(f"Mode 2: TradingView Webhooks - Instant execution on alerts")
    print(f"{'='*70}\n")

    # Run both services in parallel threads
    bot_thread = threading.Thread(target=run_autonomous_bot, daemon=True)
    webhook_thread = threading.Thread(target=run_webhook_service, daemon=True)

    bot_thread.start()
    webhook_thread.start()

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down NIJA services...")
        sys.exit(0)
