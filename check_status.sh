#!/bin/bash
tail -100 /workspaces/Nija/nija.log | grep -E "BALANCE|position|SELL|BUY|profit|loss|P&L|Trading"
