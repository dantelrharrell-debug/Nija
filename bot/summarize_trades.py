import re
from datetime import datetime

import os
LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'nija.log'))

TRADE_OPENED_PATTERN = re.compile(r"=== TRADE OPENED ===\\nTime: (.*?)\\nProduct: (.*?)\\nSide: (.*?)\\nSize: ([0-9.]+)\\nEntry: \\$([0-9.]+)\\nUSD Amount: \\$([0-9.]+)\\nMode: (.*?)\\n=+")
TRADE_CLOSED_PATTERN = re.compile(r"=== TRADE CLOSED ===\\nTime: (.*?)\\nProduct: (.*?)\\nSide: (.*?)\\nSize: ([0-9.]+)\\nEntry: \\$([0-9.]+)\\nExit: \\$([0-9.]+)\\nPnL: \\$([+-]?[0-9.]+) \\(([+-]?[0-9.]+)%\\)\\nReason: (.*?)\\nMode: (.*?)\\n=+")

def parse_trades(log_path=LOG_FILE, max_trades=10):
    with open(log_path, "r") as f:
        log = f.read()
    opened = list(TRADE_OPENED_PATTERN.finditer(log))
    closed = list(TRADE_CLOSED_PATTERN.finditer(log))
    # Only show the most recent trades
    opened = opened[-max_trades:]
    closed = closed[-max_trades:]
    print("\nRecent Opened Trades:")
    for m in opened:
        print(f"[{m.group(1)}] {m.group(2)} {m.group(3).upper()} size={m.group(4)} entry=${m.group(5)} USD=${m.group(6)} mode={m.group(7)}")
    print("\nRecent Closed Trades:")
    for m in closed:
        print(f"[{m.group(1)}] {m.group(2)} {m.group(3).upper()} size={m.group(4)} entry=${m.group(5)} exit=${m.group(6)} PnL=${m.group(7)} ({m.group(8)}%) reason={m.group(9)} mode={m.group(10)}")

if __name__ == "__main__":
    import sys
    max_trades = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    parse_trades(max_trades=max_trades)
