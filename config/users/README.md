# User Configuration Files

This directory contains user configuration files for each supported brokerage.

## Structure

Each brokerage has its own user configuration file:
- `kraken_users.json` - Users trading on Kraken
- `alpaca_users.json` - Users trading on Alpaca (stocks)
- `coinbase_users.json` - Users trading on Coinbase (future use)

## User Configuration Format

Each user configuration file is a JSON array of user objects:

```json
[
  {
    "user_id": "john_doe",
    "name": "John Doe",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Optional description"
  }
]
```

### Fields

- **user_id** (required): Unique identifier for the user (lowercase, underscores for spaces)
  - Used to match environment variables: `KRAKEN_USER_JOHN_API_KEY`
  - Format: `firstname_lastname` or just `firstname`
  
- **name** (required): Display name for the user (used in logs)
  
- **broker_type** (required): The brokerage this user account is for
  - Must match the filename (e.g., "kraken" for kraken_users.json)
  
- **enabled** (required): Whether this user account is active
  - `true` - Bot will attempt to connect and trade
  - `false` - Bot will skip this user
  
- **description** (optional): Human-readable description or notes

## Adding a New User

### Step 1: Add user to appropriate brokerage file

Edit the brokerage-specific file (e.g., `kraken_users.json`):

```json
[
  {
    "user_id": "jane_smith",
    "name": "Jane Smith",
    "broker_type": "kraken",
    "enabled": true,
    "description": "New user added on 2026-01-12"
  }
]
```

### Step 2: Set environment variables

Add the user's API credentials to your `.env` file:

For Kraken users:
```bash
KRAKEN_USER_JANE_API_KEY=your_api_key_here
KRAKEN_USER_JANE_API_SECRET=your_api_secret_here
```

For Alpaca users:
```bash
ALPACA_USER_JANE_API_KEY=your_api_key_here
ALPACA_USER_JANE_API_SECRET=your_api_secret_here
ALPACA_USER_JANE_PAPER=true  # or false for live trading
```

**Note:** The environment variable prefix is constructed from the `user_id` first name in uppercase.
- `user_id: "jane_smith"` → `KRAKEN_USER_JANE_*`
- `user_id: "john"` → `KRAKEN_USER_JOHN_*`

### Step 3: Restart the bot

The bot will automatically detect and connect the new user account on next startup.

## Environment Variable Format

### Kraken
```bash
KRAKEN_USER_{FIRSTNAME}_API_KEY=...
KRAKEN_USER_{FIRSTNAME}_API_SECRET=...
```

### Alpaca
```bash
ALPACA_USER_{FIRSTNAME}_API_KEY=...
ALPACA_USER_{FIRSTNAME}_API_SECRET=...
ALPACA_USER_{FIRSTNAME}_PAPER=true
```

### Coinbase (future)
```bash
COINBASE_USER_{FIRSTNAME}_API_KEY=...
COINBASE_USER_{FIRSTNAME}_API_SECRET=...
```

## Best Practices

1. **Use descriptive user_ids**: `firstname_lastname` format
2. **Enable only funded accounts**: Set `enabled: false` for unfunded accounts
3. **Add descriptions**: Note when users were added and why
4. **One user per brokerage**: If a user has multiple brokerage accounts, add them to each brokerage file
5. **Keep credentials secure**: Never commit `.env` files with real credentials

## Troubleshooting

### User shows "NOT TRADING (Connection failed or not configured)"

Check:
1. User is enabled in config file (`"enabled": true`)
2. Environment variables are set correctly
3. User credentials are valid on the brokerage
4. Bot has been restarted after adding user

### "Invalid user_id format" error

Ensure user_id:
- Is lowercase
- Uses underscores for spaces
- Matches pattern `^[a-z][a-z0-9_]*$`

### Environment variables not found

Environment variable names are case-sensitive and must:
- Match the pattern exactly: `{BROKER}_USER_{FIRSTNAME}_API_KEY`
- Use UPPERCASE for broker and firstname
- Extract firstname from user_id (part before first underscore)
