# GitHub Copilot Coding Agent Instructions

## Project Overview

NIJA is an autonomous cryptocurrency trading bot that connects to the Coinbase Advanced Trade API. It scans 732+ cryptocurrency markets and executes trades using a sophisticated dual RSI strategy (RSI_9 + RSI_14) with dynamic position management, automatic profit compounding, and intelligent trailing systems.

The bot operates in dual-mode:
- **Autonomous Mode**: Scans markets every 2.5 minutes
- **TradingView Webhooks**: Instant execution based on custom alerts

## Project Structure

```
/bot/                      # Core trading bot code
  ├── trading_strategy.py  # Main trading strategy implementation
  ├── nija_apex_strategy_v71.py  # APEX V7.1 strategy
  ├── broker_integration.py  # Coinbase API integration
  ├── risk_manager.py      # Risk management logic
  ├── execution_engine.py  # Trade execution
  ├── indicators.py        # Technical indicators
  ├── apex_*.py           # APEX strategy components
  └── tradingview_webhook.py  # Webhook server

/scripts/                  # Utility scripts
/*.py                     # Root-level utility scripts
/archive/                 # Historical files and old implementations
```

## Coding Standards

### Python Style
- Use **snake_case** for all variable names, function names, and file names
- Use **PascalCase** for class names
- Follow PEP 8 style guide
- Use 4 spaces for indentation (never tabs)
- Maximum line length: 120 characters
- Use type hints where appropriate for function parameters and return types

### Code Organization
- Keep functions focused and single-purpose
- Add docstrings to all classes and public functions
- Group related functionality into modules
- Avoid circular imports

### Error Handling
- Always handle API errors gracefully (Coinbase API can fail)
- Log errors with appropriate context using the logging module
- Never expose API keys or secrets in logs or error messages
- Use try-except blocks for external API calls

### Security Best Practices
- **CRITICAL**: Never commit API keys, secrets, or credentials to version control
- Use environment variables for all sensitive configuration
- Secrets are stored in `.env` file (never commit this file)
- Required secrets: `COINBASE_API_KEY`, `COINBASE_API_SECRET`, `COINBASE_PEM_CONTENT`
- Always validate and sanitize webhook inputs
- Use secure random number generation for sensitive operations

## Dependencies

### Package Management
- All Python dependencies are listed in `requirements.txt`
- Install dependencies: `pip install -r requirements.txt`
- Python version: 3.11 (specified in `runtime.txt`)
- Key dependencies:
  - `coinbase-advanced-py==1.8.2` - Coinbase API client
  - `Flask==2.3.3` - Web framework for webhooks
  - `pandas==2.1.1` - Data analysis
  - `numpy==1.26.3` - Numerical computations

### Adding New Dependencies
- Add to `requirements.txt` with pinned versions
- Test compatibility with existing packages
- Document why the dependency is needed
- Consider security implications

## Testing

### Testing Strategy
- Test files are located in `bot/test_*.py` and `archive/test_files/`
- Integration tests for Coinbase API are in `bot/test_apex_integration.py`
- Backtest scripts are in `bot/*backtest*.py`

### Running Tests
- Manual testing scripts exist but no automated test suite
- Always test Coinbase integration carefully with small amounts first
- Use paper trading mode for strategy testing before live deployment

### When Making Changes
- Test locally before deploying
- Verify indentation (past issues with IndentationError in `trading_strategy.py`)
- Test webhook endpoints if modifying webhook code
- Validate strategy logic with backtests before live deployment

## Building and Deployment

### Docker
- Build command: `docker build -t nija-bot .`
- Dockerfile is at repository root
- Container uses multi-stage build

### Running Locally
- Start script: `./start.sh` or `bash start.sh`
- The bot can run in different modes via various start scripts in `/bot/`

### Environment Setup
- Copy `.env.example` to `.env` and fill in secrets
- Required environment variables:
  - `PORT=5000` (for webhook server)
  - `WEB_CONCURRENCY=1`
  - Coinbase API credentials

### Deployment Platforms
- Railway (primary deployment platform)
- Configuration in `railway.json`
- Start command in `start.sh`

## Trading Strategy Guidelines

### Strategy Implementation
- Core strategy is in `bot/trading_strategy.py`
- APEX V7.1 strategy is the latest version: `bot/nija_apex_strategy_v71.py`
- All strategies use dual RSI indicators (RSI_9 and RSI_14)
- Position management includes trailing stops and profit targets

### Risk Management
- Maximum position sizes are calculated based on account balance
- Risk per trade is limited
- Stop losses are mandatory for all positions
- Never remove or bypass risk management checks

### Market Scanning
- Scans 732+ cryptocurrency pairs on Coinbase
- Filters markets based on liquidity and volatility
- Market filters are in `bot/market_filters.py`

## Common Tasks

### Fixing Bugs
- Check logs first to understand the error
- Common issue: indentation errors in Python
- API rate limiting: implement backoff strategies
- Verify webhook signature validation for security

### Adding New Features
- Follow the existing code structure
- Update relevant documentation (README.md, strategy docs)
- Test thoroughly before deploying
- Consider impact on existing positions

### Modifying Trading Logic
- **CRITICAL**: Changes to trading logic require extensive testing
- Always backtest strategy changes
- Document changes in commit messages
- Update strategy documentation files

## Documentation Files

- `README.md` - Main project documentation
- `APEX_V71_DOCUMENTATION.md` - APEX V7.1 strategy details
- `APEX_STRATEGY_README.md` - General APEX strategy documentation
- `BROKER_INTEGRATION_GUIDE.md` - Coinbase integration guide
- `TRADINGVIEW_SETUP.md` - TradingView webhook setup
- `IMPLEMENTATION_SUMMARY.md` - Historical implementation notes

When updating features, update relevant documentation files.

## Git Workflow

### Branch Naming
- Feature branches: `feature/description`
- Bug fixes: `fix/description`
- Copilot branches: `copilot/task-description`

### Commit Messages
- Use clear, descriptive commit messages
- Reference issue numbers when applicable
- Describe what changed and why

### Files to Never Commit
- `.env` (contains secrets)
- `*.pem` files (SSL certificates)
- `__pycache__/` directories
- `*.pyc` files
- Log files
- Local configuration overrides

## Important Notes

### Critical Files
- `bot/trading_strategy.py` - Recently fixed IndentationError (Dec 11, 2025)
- `bot/broker_integration.py` - Handles all Coinbase API interactions
- `bot/webhook_server.py` - Receives TradingView webhooks

### Known Issues
- Watch for indentation errors (common in Python)
- API rate limiting from Coinbase (implement retry logic)
- Webhook security must be maintained (validate all incoming requests)

### Best Practices for This Repository
- Always preserve working code - don't remove functional implementations
- Test API integrations with small amounts first
- Log important trading decisions for audit trail
- Keep position management logic robust and defensive
- Validate all external inputs (webhooks, API responses)
- Handle network failures gracefully (trading bot must be resilient)

## Linting and Code Quality

- No automated linting configured yet
- Follow PEP 8 manually
- Use Python formatter (black) if available: `black bot/`
- Check code before committing: `python -m py_compile <file>.py`

## Questions or Clarifications

When in doubt:
1. Check existing implementations for patterns
2. Review documentation files
3. Preserve existing functionality
4. Ask for clarification on trading logic changes (they impact real money)

## Working with Copilot

### What to Delegate to Copilot
- ✅ Bug fixes (especially syntax and indentation errors)
- ✅ Code refactoring and cleanup
- ✅ Adding error handling
- ✅ Documentation updates
- ✅ Adding logging
- ✅ Test coverage improvements

### What Requires Careful Review
- ⚠️ Trading strategy logic changes (impacts profitability)
- ⚠️ Risk management modifications (impacts capital protection)
- ⚠️ API integration changes (could break connectivity)
- ⚠️ Security-related code (webhooks, authentication)
- ⚠️ Position management logic (affects open trades)

### Issue Guidelines
- Provide specific file paths when requesting changes
- Include expected behavior and actual behavior for bugs
- Reference relevant documentation files
- Specify if changes affect live trading (require extra caution)
