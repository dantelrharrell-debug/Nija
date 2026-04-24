# NIJA Control Center - Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NIJA CONTROL CENTER                                 │
│                  Unified Operational Command Center                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐         ┌──────────────────────┐
│   CLI Dashboard      │         │   Web Dashboard      │
│                      │         │                      │
│  • Interactive Menu  │         │  • Single Page App   │
│  • Auto-Refresh      │         │  • Auto-Refresh 10s  │
│  • Keyboard Cmds     │         │  • Responsive Design │
│  • ANSI Colors       │         │  • Action Buttons    │
│                      │         │  • Visual Charts     │
│  nija_control_       │         │  control_center.html │
│  center.py           │         │  (in templates/)     │
└──────────┬───────────┘         └──────────┬───────────┘
           │                                │
           │                                │
           └────────────┬───────────────────┘
                        │
                        ▼
           ┌────────────────────────┐
           │   Control Center API   │
           │                        │
           │  Flask REST API        │
           │  • 13+ Endpoints       │
           │  • Alert Management    │
           │  • Action Handlers     │
           │  • State Management    │
           │                        │
           │  control_center_api.py │
           └────────────┬───────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
┌───────────────┐ ┌──────────┐ ┌──────────────┐
│   Database    │ │ Controls │ │ Integrations │
│               │ │          │ │              │
│ • Users       │ │ • Enable │ │ • PnL Track  │
│ • Positions   │ │ • Disable│ │ • Risk Mgr   │
│ • Trades      │ │ • Status │ │ • Brokers    │
│ • Credentials │ │          │ │ • Metrics    │
└───────────────┘ └──────────┘ └──────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA FLOW                                         │
└─────────────────────────────────────────────────────────────────────────────┘

User Action (CLI/Web)
         │
         ▼
    API Endpoint
         │
         ├──► GET Overview ──────► Aggregate from DB, Controls, PnL
         │                              │
         ├──► POST Action ──────────────┼──► Execute via Controls
         │                              │
         ├──► GET Alerts ────────────────┼──► Fetch from State
         │                              │
         └──► GET Positions ─────────────┼──► Query Database
                                        │
                                        ▼
                                   Return JSON
                                        │
                                        ▼
                          Display in CLI/Web Interface


┌─────────────────────────────────────────────────────────────────────────────┐
│                        KEY COMPONENTS                                       │
└─────────────────────────────────────────────────────────────────────────────┘

1. CLI Dashboard (nija_control_center.py)
   ├── Class: NIJAControlCenter
   ├── Methods:
   │   ├── get_platform_overview()
   │   ├── get_user_summaries()
   │   ├── get_recent_alerts()
   │   ├── display_overview()
   │   ├── display_users()
   │   ├── emergency_stop()
   │   └── run_dashboard()
   └── Features:
       ├── Auto-refresh loop
       ├── Keyboard input handling
       ├── Color-coded output
       └── Graceful degradation

2. Control Center API (control_center_api.py)
   ├── Class: ControlCenterState
   ├── Routes:
   │   ├── /api/control-center/overview
   │   ├── /api/control-center/users
   │   ├── /api/control-center/positions
   │   ├── /api/control-center/alerts
   │   ├── /api/control-center/actions/*
   │   └── /api/control-center/health
   └── Features:
       ├── Alert state management
       ├── Thread-safe operations
       ├── Error handling
       └── Integration layer

3. Web Dashboard (control_center.html)
   ├── Sections:
   │   ├── Header with last update
   │   ├── Platform Overview card
   │   ├── Quick Actions card
   │   ├── System Health card
   │   ├── Users list
   │   ├── Alerts panel
   │   └── Positions table
   └── Features:
       ├── Auto-refresh (setInterval)
       ├── Fetch API calls
       ├── Dynamic rendering
       ├── Responsive design
       └── Action confirmations

┌─────────────────────────────────────────────────────────────────────────────┐
│                      INTEGRATION POINTS                                     │
└─────────────────────────────────────────────────────────────────────────────┘

Existing Module          → Control Center Integration
─────────────────────────────────────────────────────────────
database.models          → Query Users, Positions, Trades
controls                 → Enable/disable trading, get status
bot.user_pnl_tracker     → Get balances, daily P&L
bot.user_risk_manager    → Get risk status, can_trade()
bot.broker_manager       → Broker information
bot.command_center_metrics → Performance metrics
user_status_summary.py   → Called from CLI menu


┌─────────────────────────────────────────────────────────────────────────────┐
│                       SECURITY FEATURES                                     │
└─────────────────────────────────────────────────────────────────────────────┘

✓ No Flask debug mode in production
✓ No API keys or secrets exposed
✓ Action confirmations required
✓ Thread-safe alert management
✓ Graceful error handling
✓ Input validation on actions
✓ Read-only data access (except actions)
✓ Alert logging for audit trail


┌─────────────────────────────────────────────────────────────────────────────┐
│                      DEPLOYMENT OPTIONS                                     │
└─────────────────────────────────────────────────────────────────────────────┘

1. Integrated Mode (Recommended)
   python bot/dashboard_server.py
   → Serves all dashboards including Control Center
   → Port 5001
   → Access at /control-center

2. Standalone API Mode
   python control_center_api.py
   → Only Control Center API
   → Port 5002
   → For custom frontends

3. CLI Only Mode
   python nija_control_center.py
   → Terminal-based dashboard
   → No web server needed
   → Direct database access


┌─────────────────────────────────────────────────────────────────────────────┐
│                         FUTURE ENHANCEMENTS                                 │
└─────────────────────────────────────────────────────────────────────────────┘

Potential additions (not implemented):
□ WebSocket for real-time push updates
□ Advanced filtering and search
□ Historical charts and trends
□ Export to PDF/CSV
□ Mobile app integration
□ Multi-user access control
□ Custom alert rules engine
□ Position management (close/modify)
□ Trade execution from dashboard
□ Integration with external monitoring tools


┌─────────────────────────────────────────────────────────────────────────────┐
│                       FILE STRUCTURE                                        │
└─────────────────────────────────────────────────────────────────────────────┘

/home/runner/work/Nija/Nija/
├── nija_control_center.py          (CLI Dashboard - 492 lines)
├── control_center_api.py            (REST API - 565 lines)
├── demo_control_center.py           (Demo Script - 91 lines)
├── CONTROL_CENTER.md                (Documentation - 365 lines)
├── CONTROL_CENTER_QUICKSTART.md     (Quick Start - 125 lines)
├── CONTROL_CENTER_ARCHITECTURE.md   (This file)
├── bot/
│   ├── dashboard_server.py          (Updated with Control Center)
│   └── templates/
│       └── control_center.html      (Web UI - 751 lines)
└── README.md                        (Updated with Control Center section)

Total: ~2,500 lines of new code + documentation
```
