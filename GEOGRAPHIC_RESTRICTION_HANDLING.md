# Geographic Restriction Handling

## Overview

NIJA now automatically detects and blacklists cryptocurrency symbols that cannot be traded due to geographic restrictions. This prevents the bot from repeatedly attempting to trade restricted assets.

## Problem Solved

Previously, when NIJA attempted to trade a geographically restricted asset (e.g., KMNO in Washington state), the trade would be rejected by the exchange. However, the bot would continue scanning and attempting to trade the same symbol in future cycles, wasting opportunities and preventing successful trades on non-restricted assets.

**Example Error:**
```
ERROR: EAccount:Invalid permissions:KMNO trading restricted for US:WA.
```

## How It Works

### 1. Automatic Detection

When a trade is rejected by the exchange, NIJA checks if the error message indicates a geographic restriction:

- "trading restricted"
- "restricted for US:"
- "not available in your region"
- "geographic restriction"
- "invalid permissions"
- "region not supported"

### 2. Blacklist Addition

If a geographic restriction is detected:
1. The symbol is automatically added to the persistent blacklist
2. Both symbol formats are blacklisted (e.g., "KMNO-USD" and "KMNOUSD")
3. The restriction reason is saved for reference
4. The blacklist is persisted to `bot/restricted_symbols.json`

### 3. Future Prevention

On bot startup:
1. The blacklist is loaded from `bot/restricted_symbols.json`
2. Restricted symbols are merged with `DISABLED_PAIRS`
3. Market scanning filters out all blacklisted symbols
4. The bot will never attempt to trade these symbols again

## Blacklist File Location

**File:** `bot/restricted_symbols.json`

**Format:**
```json
{
  "symbols": [
    "KMNO-USD",
    "KMNOUSD"
  ],
  "reasons": {
    "KMNO-USD": "trading restricted for US:WA",
    "KMNOUSD": "trading restricted for US:WA"
  },
  "last_updated": "2026-01-28T01:21:51.347391"
}
```

## Viewing Restricted Symbols

The blacklist is automatically logged on bot startup:

```
📋 Loaded 2 geographically restricted symbols
   Restricted: KMNO-USD, KMNOUSD
```

## Manually Adding Symbols

You can manually add symbols to the blacklist by editing `bot/restricted_symbols.json`:

```json
{
  "symbols": [
    "SYMBOL-USD",
    "SYMBOLUSD"
  ],
  "reasons": {
    "SYMBOL-USD": "Your reason here",
    "SYMBOLUSD": "Your reason here"
  },
  "last_updated": "2026-01-28T00:00:00.000000"
}
```

**Note:** Always include both the dash and no-dash formats of the symbol for maximum compatibility across exchanges.

## Removing Symbols

If a symbol becomes available in your region:

1. Edit `bot/restricted_symbols.json`
2. Remove the symbol from both the `symbols` array and `reasons` object
3. Restart the bot

## Technical Implementation

### Files Modified

1. **bot/restricted_symbols.py** (new)
   - `RestrictedSymbolsManager` class
   - Persistent blacklist management
   - Symbol normalization
   - Error detection logic

2. **bot/execution_engine.py**
   - Catches `OrderRejectedError` exceptions
   - Detects geographic restrictions from error messages
   - Automatically adds symbols to blacklist

3. **bot/trading_strategy.py**
   - Loads restricted symbols on startup
   - Merges with existing `DISABLED_PAIRS`

4. **bot/restricted_symbols.json** (new)
   - Persistent storage of restricted symbols

### Symbol Normalization

The system handles multiple symbol formats:

- `KMNO-USD` → blacklists both `KMNO-USD` and `KMNOUSD`
- `KMNOUSD` → blacklists both `KMNOUSD` and `KMNO-USD`

This ensures compatibility across exchanges that use different symbol formats.

## Benefits

1. **Prevents Wasted Opportunities:** Bot can focus on tradeable assets
2. **Reduces API Calls:** No repeated attempts on restricted symbols
3. **Automatic Learning:** Bot learns from rejections without manual intervention
4. **Persistent Memory:** Blacklist survives bot restarts
5. **Multi-Exchange Support:** Works with Coinbase, Kraken, and other exchanges

## Logs

When a geographic restriction is detected, you'll see:

```
═══════════════════════════════════════════════════════════
🚫 GEOGRAPHIC RESTRICTION DETECTED
═══════════════════════════════════════════════════════════
   Symbol: KMNO-USD
   Error: EAccount:Invalid permissions:KMNO trading restricted for US:WA
   Adding to permanent blacklist to prevent future attempts
═══════════════════════════════════════════════════════════
🚫 Added to restriction blacklist: KMNO-USD
   Reason: EAccount:Invalid permissions:KMNO trading restricted for US:WA
🚫 Added to restriction blacklist: KMNOUSD
   Reason: EAccount:Invalid permissions:KMNO trading restricted for US:WA
💾 Saved restriction blacklist (2 symbols)
```

## Future Enhancements

Potential improvements:
- Web dashboard to view/manage blacklist
- API endpoint to query restricted symbols
- Automatic removal of symbols when restrictions are lifted
- Region-specific blacklists for multi-user deployments
- Integration with exchange API to proactively fetch restricted symbols

## Troubleshooting

### Blacklist Not Loading

If restricted symbols aren't being filtered:
1. Check that `bot/restricted_symbols.json` exists
2. Verify JSON syntax is valid
3. Check bot logs for "Loaded X restricted symbols" message
4. Ensure `DISABLED_PAIRS` includes the symbols

### Symbol Still Being Traded

If a blacklisted symbol is still being traded:
1. Verify both symbol formats are in the blacklist
2. Check that the symbol in logs matches the blacklist format
3. Restart the bot to reload the blacklist
4. Check for typos in the symbol name

### Blacklist File Missing

The blacklist file is created automatically when the first geographic restriction is detected. If the file doesn't exist on startup, it's created as an empty blacklist.

## Support

For issues or questions:
1. Check bot logs for error messages
2. Verify `bot/restricted_symbols.json` syntax
3. Review this documentation
4. Contact support with log excerpts showing the issue
