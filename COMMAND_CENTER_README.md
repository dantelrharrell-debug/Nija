# NIJA Command Center

The NIJA Command Center is a comprehensive live dashboard that provides real-time visibility into 8 critical performance metrics for the NIJA trading bot.

## Features

The Command Center displays the following metrics:

### 1. ✅ Equity Curve
- Current portfolio equity
- Peak equity (all-time high)
- 24-hour change ($ and %)
- Historical equity chart

### 2. ✅ Risk Heat
- Risk score (0-100 scale)
- Risk level: LOW, MODERATE, HIGH, or CRITICAL
- Maximum drawdown percentage
- Current drawdown percentage
- Position concentration

### 3. ✅ Trade Quality Score
- Quality score (0-100 scale)
- Letter grade (A+ to F)
- Win rate percentage
- Profit factor
- Average win/loss ratio

### 4. ✅ Signal Accuracy
- Signal accuracy percentage
- Total signals generated
- Successful signals
- Failed signals
- False positive rate

### 5. ✅ Slippage
- Average slippage in basis points (bps)
- Average slippage in USD
- Total slippage cost
- Impact on profit percentage

### 6. ✅ Fee Impact
- Total fees paid
- Fees as percentage of profit
- Average fee per trade
- Fee efficiency score (0-100)

### 7. ✅ Strategy Efficiency
- Efficiency score (0-100)
- Trades per day
- Win rate efficiency
- Capital utilization percentage

### 8. ✅ Capital Growth Velocity
- Annualized growth rate
- Daily growth rate
- Monthly growth rate

## Quick Start

### 1. Generate Sample Data

Run the test script to generate sample trading data:

```bash
python bot/test_command_center.py
```

This will:
- Initialize the metrics tracker with $10,000
- Generate 7 days of equity curve data
- Create 50 sample trades
- Display a metrics summary
- Save the data for the dashboard

### 2. Start the Dashboard Server

```bash
python bot/dashboard_server.py
```

The server will start on port 5001.

### 3. Access the Command Center

Open your browser and navigate to:

```
http://localhost:5001/command-center
```

## Dashboard Features

- **Auto-refresh**: Updates every 5 seconds
- **Live Charts**: Interactive equity curve chart using Chart.js
- **Responsive Design**: Works on desktop, tablet, and mobile
- **Modern UI**: Gradient backgrounds, smooth animations, and professional styling
- **Color-Coded Metrics**: Green for positive, red for negative, contextual colors

## API Endpoints

The Command Center provides the following REST API endpoints:

### Get All Metrics
```
GET /api/command-center/metrics
```

Returns a complete snapshot of all 8 metrics.

### Get Individual Metrics

- `GET /api/command-center/equity-curve?hours=24` - Equity curve data
- `GET /api/command-center/risk-heat` - Risk heat metrics
- `GET /api/command-center/trade-quality` - Trade quality score
- `GET /api/command-center/signal-accuracy` - Signal accuracy metrics
- `GET /api/command-center/slippage` - Slippage metrics
- `GET /api/command-center/fee-impact` - Fee impact metrics
- `GET /api/command-center/strategy-efficiency` - Strategy efficiency
- `GET /api/command-center/growth-velocity` - Capital growth velocity

### Health Check
```
GET /api/command-center/health
```

## Integration with Trading Bot

To integrate the Command Center with your live trading bot:

### 1. Import the Metrics Tracker

```python
from bot.command_center_metrics import get_command_center_metrics

# Initialize metrics tracker
metrics = get_command_center_metrics(initial_capital=1000.0)
```

### 2. Update Equity

Call this periodically (e.g., every hour or on every trade):

```python
metrics.update_equity(
    equity=current_portfolio_value,
    cash=available_cash,
    positions_value=total_position_value
)
```

### 3. Record Trades

After each completed trade:

```python
metrics.record_trade(
    symbol='BTC-USD',
    side='long',  # or 'short'
    entry_price=45000.0,
    exit_price=46000.0,
    size=1000.0,  # Position size in USD
    fees=1.0,
    slippage=0.5  # Optional
)
```

### 4. Record Signals

When your strategy generates trading signals:

```python
metrics.record_signal(success=True)  # or False if signal failed
```

### 5. Save State (Optional)

The metrics tracker automatically saves state, but you can manually trigger it:

```python
metrics._save_state()
```

## File Structure

```
bot/
├── command_center_metrics.py     # Core metrics calculation engine
├── command_center_api.py          # Flask API endpoints
├── test_command_center.py         # Test script with sample data
├── templates/
│   └── command_center.html        # Dashboard UI
└── dashboard_server.py            # Main dashboard server (includes Command Center)

data/
└── command_center_metrics.json    # Persisted metrics data
```

## Data Persistence

All metrics are automatically saved to `data/command_center_metrics.json` and loaded on startup. This ensures your metrics persist across restarts.

## Customization

### Change Lookback Period

By default, the metrics tracker keeps 30 days of history. To change this:

```python
metrics = get_command_center_metrics(
    initial_capital=1000.0,
    lookback_days=60  # Keep 60 days of history
)
```

### Adjust Auto-Refresh Interval

Edit `bot/templates/command_center.html` and change:

```javascript
const REFRESH_INTERVAL = 5000; // milliseconds (5 seconds)
```

## Troubleshooting

### Dashboard Shows Zero Values

If the dashboard shows all zeros:
1. Run `python bot/test_command_center.py` to generate sample data
2. Refresh the dashboard
3. Verify the file `data/command_center_metrics.json` exists

### Server Won't Start

Ensure dependencies are installed:

```bash
pip install Flask==2.3.3 Flask-CORS==4.0.0 psutil
```

### API Returns 500 Errors

Check the server logs for error details. Common issues:
- Metrics data file is corrupted (delete `data/command_center_metrics.json` and regenerate)
- Import errors (ensure all bot modules are in Python path)

## Navigation

From the main dashboard (http://localhost:5001/), click the "⚡ Command Center" button to access the Command Center.

From the Command Center, you can return to:
- Main Dashboard (http://localhost:5001/)
- Users Dashboard (http://localhost:5001/users)
- Trade Ledger (http://localhost:5001/trades)

## Production Deployment

For production use:

1. Use a production WSGI server (gunicorn, uWSGI)
2. Set up reverse proxy (nginx, Apache)
3. Enable HTTPS/SSL
4. Configure authentication
5. Set appropriate CORS policies

Example with gunicorn:

```bash
gunicorn -w 4 -b 0.0.0.0:5001 bot.dashboard_server:app
```

## Future Enhancements

Potential future additions:
- Export metrics to CSV/JSON
- Historical metric comparisons
- Alert thresholds
- Email/SMS notifications
- Multi-timeframe analysis
- Strategy comparison charts
- Real-time trade feed
- Advanced risk analytics

## Support

For issues or questions about the Command Center, please check:
- Repository issues: https://github.com/dantelrharrell-debug/Nija/issues
- Documentation: See other MD files in the repository
- Code comments in the source files

## Version History

- **v1.0** (January 30, 2026) - Initial release
  - 8 core metrics
  - Live dashboard UI
  - REST API
  - Data persistence
  - Sample data generator
