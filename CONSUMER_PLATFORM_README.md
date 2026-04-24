# NIJA Consumer Platform - Architecture Documentation

## 🏗️ System Architecture

NIJA is now a production-grade, multi-tier trading platform with proper layer separation to protect proprietary strategy logic while providing safe, consumer-friendly access.

```
┌─────────────────────────────────────────────────────────────┐
│                     CLIENT APPLICATIONS                      │
├─────────────────────────────────────────────────────────────┤
│   [ iOS App ]   [ Android App ]   [ Web Dashboard ]         │
│                         ↓ ↓ ↓                               │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│               LAYER 3 - API GATEWAY (PUBLIC)                 │
├─────────────────────────────────────────────────────────────┤
│  File: gateway.py                                            │
│                                                              │
│  • User Authentication (JWT)                                 │
│  • Account Management                                        │
│  • Broker API Key Management (encrypted)                     │
│  • Trading Controls (start/stop/pause)                       │
│  • Statistics & Reporting                                    │
│  • Rate Limiting & Security                                  │
│                                                              │
│  🔒 SECURITY: No strategy logic exposed                      │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│          LAYER 2 - USER CONTROL BACKEND (LIMITED)            │
├─────────────────────────────────────────────────────────────┤
│  File: user_control.py                                       │
│                                                              │
│  • User Instance Management                                  │
│  • Isolated Execution per User                               │
│  • Risk Limit Enforcement                                    │
│  • Capital Isolation                                         │
│  • Position Tracking                                         │
│  • Statistics Aggregation                                    │
│                                                              │
│  🔒 ISOLATION: Each user in separate container/process       │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│            LAYER 1 - CORE BRAIN (PRIVATE)                    │
├─────────────────────────────────────────────────────────────┤
│  Files: core/, bot/trading_strategy.py, bot/apex_*.py       │
│                                                              │
│  • Proprietary Trading Strategy                              │
│  • AI/ML Models & Logic                                      │
│  • Signal Generation                                         │
│  • Entry/Exit Logic                                          │
│  • Risk Management Algorithms                                │
│                                                              │
│  🔒 PRIVATE: Never exposed to users or public API            │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                  EXCHANGE INTEGRATIONS                       │
├─────────────────────────────────────────────────────────────┤
│  Coinbase | Kraken | Binance | OKX | Alpaca                 │
└─────────────────────────────────────────────────────────────┘
```

## 🎯 Key Design Principles

### 1. **Layer Separation**
- **Layer 3 (Public)**: Users can only view stats and control trading (on/off)
- **Layer 2 (Limited)**: Manages isolated execution instances per user
- **Layer 1 (Private)**: Strategy logic is completely hidden and protected

### 2. **User Isolation**
- Each user runs in an isolated execution environment
- No cross-user capital bleeding
- No cross-user risk contamination
- One user's losses don't affect other users

### 3. **Strategy Protection**
- Strategy logic never exposed via API
- No strategy parameters in responses
- Users can't see signals, indicators, or entry/exit logic
- IP remains protected

### 4. **Security**
- JWT token-based authentication
- Encrypted API key storage
- HTTPS/TLS in production
- Rate limiting per user
- Permission-based access control

## 📁 File Structure

```
/home/runner/work/Nija/Nija/
│
├── gateway.py                  # Layer 3 - Public API Gateway
├── user_control.py            # Layer 2 - User Control Backend
├── api_server.py              # [DEPRECATED] Use gateway.py instead
├── web_server.py              # [DEPRECATED] Use gateway.py instead
│
├── auth/                      # Authentication & User Management
│   └── __init__.py           # APIKeyManager, UserManager
│
├── execution/                 # Execution Layer Interfaces
│   └── __init__.py           # UserPermissions, PermissionValidator
│
├── core/                      # Layer 1 - PRIVATE Strategy Logic
│   └── __init__.py           # Access control for core strategy
│
├── bot/                       # Trading Engine Components
│   ├── trading_strategy.py   # Main strategy implementation
│   ├── apex_*.py             # APEX strategy components
│   ├── broker_integration.py # Exchange integrations
│   └── ...
│
├── frontend/                  # Web Application
│   ├── templates/
│   │   └── index.html        # Single-page web app
│   └── static/
│       ├── css/
│       │   └── style.css     # Styling
│       ├── js/
│       │   └── app.js        # Frontend logic
│       └── manifest.json     # PWA manifest
│
└── ui/                        # UI Layer Components
    └── __init__.py           # Dashboard API
```

## 🚀 Getting Started

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

The platform uses Flask for the API server and CORS for cross-origin support.

### 2. Set Environment Variables

```bash
# JWT Secret (generate with: python -c "import secrets; print(secrets.token_hex(32))")
export JWT_SECRET_KEY="your-secret-key-here"

# Server Configuration
export PORT=5000
export FLASK_DEBUG=false

# (Optional) Existing NIJA environment variables
export COINBASE_API_KEY="..."
export COINBASE_API_SECRET="..."
# ... other broker credentials
```

### 3. Start the Platform

```bash
# Start the API Gateway + Web Frontend
python gateway.py
```

This starts:
- **Frontend**: http://localhost:5000/
- **API**: http://localhost:5000/api/

### 4. Access the Web Application

Open your browser to `http://localhost:5000/` and:
1. **Register** a new account (or login if you have one)
2. **Add broker credentials** (Coinbase, Kraken, etc.)
3. **Start trading** with the on/off controls
4. **Monitor stats** in real-time

## 🔐 Security Features

### Authentication
- **JWT Tokens**: Secure, stateless authentication
- **Token Expiration**: 24-hour default (configurable)
- **Password Hashing**: SHA256 (TODO: upgrade to bcrypt/argon2)

### API Key Protection
- **Encryption**: All broker API keys encrypted at rest
- **Never Logged**: API keys never appear in logs
- **Secure Storage**: Uses Fernet symmetric encryption

### Access Control
- **Layer Isolation**: Public API cannot access strategy logic
- **User Permissions**: Per-user trading limits and risk caps
- **Rate Limiting**: Prevents API abuse (TODO: implement)

## 📱 Progressive Web App (PWA)

The web frontend is a PWA that can be installed on mobile devices:

1. Open the web app on your phone
2. Tap "Add to Home Screen"
3. Use it like a native app!

Features:
- **Offline Support**: (TODO) View cached data when offline
- **Push Notifications**: (TODO) Get alerts for trades
- **Mobile-Optimized**: Responsive design for all screen sizes

## 🔌 API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and get JWT token

### User Management
- `GET /api/user/profile` - Get user profile
- `GET /api/user/settings` - Get user settings
- `PUT /api/user/settings` - Update user settings

### Broker Management
- `GET /api/user/brokers` - List configured brokers
- `POST /api/user/brokers/<broker>` - Add broker credentials
- `DELETE /api/user/brokers/<broker>` - Remove broker credentials

### Trading Control
- `POST /api/trading/control` - Start/stop/pause trading
- `GET /api/trading/status` - Get trading status
- `GET /api/trading/positions` - Get active positions
- `GET /api/trading/history` - Get trade history

### Statistics
- `GET /api/user/stats` - Get trading statistics

## 🏭 Production Deployment

### Docker Deployment

```dockerfile
# Dockerfile already exists in the repo
docker build -t nija-platform .
docker run -p 5000:5000 -e JWT_SECRET_KEY="..." nija-platform
```

### Kubernetes Deployment

For user isolation, deploy separate pods per user:

```yaml
# TODO: Create k8s manifests
# - StatefulSet for user execution instances
# - Service for API Gateway
# - Ingress for HTTPS
```

### Environment Recommendations

**Development:**
- Single gateway instance
- In-memory user instances
- SQLite database

**Production:**
- Load-balanced gateway (3+ instances)
- Kubernetes for user execution pods
- PostgreSQL database
- Redis for session management
- HTTPS/TLS with Let's Encrypt

## 🔄 Migration from Old NIJA

If you're migrating from the old NIJA setup:

1. **Keep existing bot code**: Layer 1 (core/) and bot/ directories remain unchanged
2. **Add new layers**: gateway.py and user_control.py wrap your existing engine
3. **Update start script**: Use `python gateway.py` instead of `python bot.py`
4. **Environment variables**: All existing env vars still work

**Your strategy logic is not modified** - it's just wrapped in secure layers.

## 📊 User Subscription Tiers

| Tier | Max Position | Max Daily Loss | Max Positions |
|------|--------------|----------------|---------------|
| Basic | $100 | $50 | 3 |
| Pro | $1,000 | $500 | 10 |
| Enterprise | $10,000 | $5,000 | Unlimited |

## 🐛 Troubleshooting

### "Module not found" errors
```bash
# Ensure you're in the NIJA directory
cd /home/runner/work/Nija/Nija

# Install dependencies
pip install -r requirements.txt
```

### "Frontend not loading"
```bash
# Check that frontend files exist
ls -la frontend/templates/index.html
ls -la frontend/static/

# Restart the server
python gateway.py
```

### "Invalid token" errors
```bash
# Clear your browser's localStorage
# In browser console: localStorage.clear()

# Or logout and login again
```

## 🎓 Development Guide

### Adding New API Endpoints

Edit `gateway.py`:

```python
@app.route('/api/your/endpoint', methods=['GET'])
@require_auth
def your_endpoint():
    user_id = request.user_id  # From JWT token
    # Your logic here
    return jsonify({'data': 'value'})
```

### Adding New Frontend Pages

1. Edit `frontend/templates/index.html` - Add HTML
2. Edit `frontend/static/css/style.css` - Add styles
3. Edit `frontend/static/js/app.js` - Add JavaScript logic

### Modifying Strategy Logic (Layer 1)

⚠️ **Important**: Never expose strategy logic via the API!

Edit files in `bot/` and `core/` as needed, but ensure:
- No strategy parameters in API responses
- No signals/indicators exposed
- Only aggregated statistics shared with users

## 📝 TODO List

### High Priority
- [ ] Replace in-memory user storage with PostgreSQL/SQLite
- [ ] Implement actual execution engine integration (Layer 2 → bot/)
- [ ] Add password hashing with bcrypt/argon2
- [ ] Implement rate limiting
- [ ] Add API request logging
- [ ] Create database migrations

### Medium Priority
- [ ] Add WebSocket support for real-time updates
- [ ] Implement trade history pagination
- [ ] Add email verification
- [ ] Add password reset flow
- [ ] Create admin dashboard
- [ ] Add billing/subscription management

### Low Priority
- [ ] iOS native app
- [ ] Android native app
- [ ] Push notifications
- [ ] Advanced charts and analytics
- [ ] Social features (leaderboard, etc.)

## 📚 Additional Documentation

- [APEX_V71_DOCUMENTATION.md](APEX_V71_DOCUMENTATION.md) - Strategy details
- [BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md) - Exchange setup
- [TRADINGVIEW_SETUP.md](TRADINGVIEW_SETUP.md) - TradingView webhooks
- [SECURITY.md](SECURITY.md) - Security best practices

## 🤝 Support

For issues or questions:
1. Check this documentation first
2. Review the code comments in gateway.py and user_control.py
3. Check the GitHub issues

## 📄 License

[Your License Here]

---

**Built with ❤️ for safe, consumer-friendly algorithmic trading**
