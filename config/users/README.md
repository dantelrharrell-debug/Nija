# User Configuration Files

This directory contains user configuration files organized by account type and brokerage.

## Configuration Formats

NIJA supports two configuration formats:

### 1. JSON Format (Recommended for production - uses environment variables)

Configuration files are organized by account type (retail/investor) and brokerage:
- `retail_kraken.json` - Retail users trading on Kraken
- `retail_alpaca.json` - Retail users trading on Alpaca (stocks)
- `retail_coinbase.json` - Retail users trading on Coinbase (future use)
- `investor_kraken.json` - Investor accounts trading on Kraken
- `investor_alpaca.json` - Investor accounts trading on Alpaca (stocks)
- `investor_coinbase.json` - Investor accounts trading on Coinbase (future use)

Individual user files:
- `daivon_frazier.json` - Individual user configuration
- `tania_gilbert.json` - Individual user configuration

### 2. YAML Format (Alternative - embedded credentials)

Individual YAML files with embedded API credentials:
- `daivon_frazier.yaml` - YAML config with API keys
- `tania_gilbert.yaml` - YAML config with API keys

**IMPORTANT SECURITY NOTE:**
- YAML files with API keys are automatically excluded from git via `.gitignore`
- Never commit YAML files containing real API credentials
- Use `user.yaml.example` as a template

## User Configuration Format

### JSON Format (with environment variables)

Each user configuration file is a JSON array of user objects:

```json
[
  {
    "user_id": "john_doe",
    "name": "John Doe",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Optional description"
  }
]
```

### YAML Format (with embedded credentials)

Each user has an individual YAML file (e.g., `daivon_frazier.yaml`):

```yaml
broker: KRAKEN
api_key: YOUR_API_KEY_HERE
api_secret: YOUR_API_SECRET_HERE
enabled: true
independent_trading: true
```

**YAML Configuration Fields:**
- **broker** (required): The brokerage (e.g., `KRAKEN`, `COINBASE`, `ALPACA`)
- **api_key** (required): User's API key from the exchange
- **api_secret** (required): User's API secret from the exchange
- **enabled** (required): Whether this account is active (`true` or `false`)
- **independent_trading** (required): Whether account trades independently (always `true`)
- **risk_multiplier** (optional): Risk multiplier (default: 1.0)

**Example YAML Configuration:**

To create a new user configuration:
1. Copy `user.yaml.example` to `<username>.yaml` (e.g., `tania_gilbert.yaml`)
2. Fill in the broker, API key, and API secret
3. Set `enabled: true` to activate
4. File will be automatically excluded from git

### Fields

- **user_id** (required): Unique identifier for the user (lowercase, underscores for spaces)
  - Used to match environment variables: `KRAKEN_USER_JOHN_API_KEY`
  - Format: `firstname_lastname` or just `firstname`

- **name** (required): Display name for the user (used in logs)

- **account_type** (required): Type of account
  - `"retail"` - Individual retail trading account
  - `"investor"` - Investor/institutional account
  - Must match the filename (e.g., "retail" for retail_kraken.json)

- **broker_type** (required): The brokerage this user account is for
  - Must match the filename (e.g., "kraken" for retail_kraken.json)

- **enabled** (required): Whether this user account is active
  - `true` - Bot will attempt to connect and trade
  - `false` - Bot will skip this user (use this when credentials are not configured)

- **description** (optional): Human-readable description or notes

## Adding a New User

### Step 1: Add user to appropriate account type and brokerage file

Edit the appropriate file (e.g., `retail_kraken.json` for a retail Kraken account):

```json
[
  {
    "user_id": "jane_smith",
    "name": "Jane Smith",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "New user added on 2024-01-14"
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
2. **Enable only funded accounts with credentials**: Set `enabled: false` for accounts without API credentials configured
3. **Add descriptions**: Note when users were added and why
4. **One user per brokerage**: If a user has multiple brokerage accounts, add them to the corresponding file for each account type and brokerage combination
5. **Keep credentials secure**: Never commit `.env` files with real credentials
6. **Disable before removing credentials**: If removing a user's API credentials, first set `enabled: false` in the config file

## Troubleshooting

### User shows "NOT TRADING (Connection failed)"

This message appears when a user is enabled but credentials are not configured or invalid.

**Solution:**
1. If credentials are not configured: Set `"enabled": false` in the config file to avoid connection attempts
2. If credentials should be configured: Check environment variables are set correctly
3. Verify user credentials are valid on the brokerage
4. Restart the bot after making changes

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
