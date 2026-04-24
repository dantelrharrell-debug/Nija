# YAML User Configuration Guide

## Overview

NIJA now supports YAML-based user configuration files with embedded API credentials as an alternative to the JSON format with environment variables.

## Quick Start

### 1. Create Your YAML Configuration

Copy the example template:
```bash
cp config/users/user.yaml.example config/users/your_username.yaml
```

### 2. Edit the Configuration

Edit your YAML file with your exchange credentials:

```yaml
broker: KRAKEN
api_key: YOUR_ACTUAL_API_KEY_FROM_KRAKEN
api_secret: YOUR_ACTUAL_API_SECRET_FROM_KRAKEN
enabled: true
copy_from_platform: true
```

### 3. Supported Brokers

- `KRAKEN` - Kraken cryptocurrency exchange
- `COINBASE` - Coinbase Advanced Trade
- `ALPACA` - Alpaca stock trading (future)

### 4. Configuration Fields

| Field | Required | Description | Default |
|-------|----------|-------------|---------|
| `broker` | Yes | Exchange name (KRAKEN, COINBASE, ALPACA) | - |
| `api_key` | Yes | Your API key from the exchange | - |
| `api_secret` | Yes | Your API secret from the exchange | - |
| `enabled` | Yes | Enable/disable this user (`true`/`false`) | `true` |
| `independent_trading` | Yes | Account trades independently | `true` |
| `risk_multiplier` | No | Risk adjustment multiplier | `1.0` |

## Security

### IMPORTANT: API Keys in YAML Files

⚠️ **SECURITY NOTICE:**
- YAML files with API keys are automatically excluded from git
- Never commit YAML files containing real API credentials
- The `.gitignore` pattern `config/users/*.yaml` protects these files
- Only `*.yaml.example` files are tracked in git

### Best Practices

1. **Never share your YAML configuration files**
2. **Use read-only API keys** when possible
3. **Enable exchange IP whitelisting** if available
4. **Disable withdrawal permissions** on API keys
5. **Rotate API keys regularly**

## Examples

### Example 1: Kraken User

```yaml
broker: KRAKEN
api_key: XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
api_secret: iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
enabled: true
copy_from_platform: true
```

### Example 2: Conservative Risk User

```yaml
broker: KRAKEN
api_key: your_api_key
api_secret: your_api_secret
enabled: true
copy_from_platform: true
risk_multiplier: 0.5  # Take half the risk of platform account
```

### Example 3: Disabled User

```yaml
broker: KRAKEN
api_key: your_api_key
api_secret: your_api_secret
enabled: false  # Temporarily disabled
copy_from_platform: true
```

## Loading YAML Configurations

### In Python Code

```python
from config.yaml_user_loader import get_yaml_user_config_loader

# Load all YAML user configurations
loader = get_yaml_user_config_loader(hard_fail=False)

# Get enabled users
enabled_users = loader.get_enabled_users()
for user in enabled_users:
    print(f"User: {user.name}, Broker: {user.broker}")

# Get specific user
user = loader.get_user_by_id("tania_gilbert")
if user and user.has_valid_credentials():
    print(f"Valid credentials for {user.name}")
```

### Hard Fail Mode

For production deployments where users must be configured:

```python
loader = get_yaml_user_config_loader(hard_fail=True)
# Raises exception if expected users are missing or have invalid credentials
```

## Validation

The YAML loader validates:

✅ **File exists and is readable**
✅ **Valid YAML syntax**
✅ **Required fields present** (broker, api_key, api_secret, enabled, copy_from_platform)
✅ **Non-placeholder credentials** (detects "YOUR_KEY", "YOUR_API_KEY_HERE", etc.)
✅ **Non-empty values**

## Troubleshooting

### Issue: "Invalid/Placeholder Credentials"

**Problem:** You're seeing warnings about placeholder credentials.

**Solution:** Replace `YOUR_KEY` and `YOUR_SECRET` with real API keys from your exchange.

### Issue: "User YAML file not found"

**Problem:** The loader can't find your YAML file.

**Solution:**
1. Ensure the file is in `config/users/` directory
2. Filename should be `username.yaml` (e.g., `tania_gilbert.yaml`)
3. Don't use `.example` extension for real configs

### Issue: "Invalid YAML format"

**Problem:** YAML syntax error in your configuration file.

**Solution:**
1. Check indentation (use spaces, not tabs)
2. Ensure colons have spaces after them: `broker: KRAKEN` (not `broker:KRAKEN`)
3. No extra quotes around values unless they contain special characters

## Migration from JSON

If you're currently using JSON configs with environment variables:

### Before (JSON + Environment Variables)
```json
{
  "name": "Tania Gilbert",
  "broker": "kraken",
  "enabled": true
}
```

```bash
# .env file
KRAKEN_USER_TANIA_API_KEY=...
KRAKEN_USER_TANIA_API_SECRET=...
```

### After (YAML)
```yaml
broker: KRAKEN
api_key: ...
api_secret: ...
enabled: true
copy_from_platform: true
```

**Benefits of YAML:**
- ✅ All configuration in one file
- ✅ Easier to manage per-user settings
- ✅ No need to set environment variables
- ✅ Still excluded from git for security

**Benefits of JSON + Env Vars:**
- ✅ Centralized credential management
- ✅ Easier to rotate keys (just update .env)
- ✅ Better for containerized deployments

## FAQs

### Q: Can I use both JSON and YAML configs?

A: Yes! The system supports both formats. Configure which loader to use in your application code.

### Q: What happens if I commit my YAML file?

A: The `.gitignore` pattern should prevent this, but if you accidentally commit it, immediately:
1. Rotate your API keys on the exchange
2. Remove the file from git history
3. Update your YAML file with new keys

### Q: Can I share the same API keys between users?

A: Not recommended. Each user should have their own API keys for:
- Better tracking and auditing
- Individual rate limits
- Security isolation

### Q: How do I disable a user temporarily?

A: Set `enabled: false` in the YAML file. The user will be loaded but not activated.

## Support

For issues or questions:
- Check `config/users/README.md` for detailed field documentation
- Review `USER_MANAGEMENT.md` for user lifecycle management
- File an issue on GitHub with the `user-config` label

---

**Version:** 1.0
**Last Updated:** January 21, 2026
**Status:** ✅ YAML Configuration Support Active
