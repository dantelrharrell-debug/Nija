# NIJA Operator Quick Reference Cards

Two versions of a consolidated quick reference guide for NIJA trading bot operators.

## 📄 Available Versions

### 1. Markdown Version (Text-Based)
**File:** `NIJA_OPERATOR_QUICK_REFERENCE.md`

- ✅ Plain text format, easily viewable in any text editor
- ✅ Perfect for terminal/CLI environments
- ✅ Copy-paste friendly commands
- ✅ Searchable with grep/find
- ✅ Version control friendly
- ✅ Printable via markdown-to-PDF tools

**Use when:**
- Working in SSH/terminal environment
- Need to quickly search for commands
- Want to print a physical reference card
- Prefer simple text format

### 2. HTML Version (Styled with Icons & Color Coding)
**File:** `NIJA_OPERATOR_QUICK_REFERENCE.html`

- ✅ Beautiful visual design with color coding
- ✅ Icon indicators for different sections
- ✅ Interactive hover effects
- ✅ Responsive design (mobile/tablet/desktop)
- ✅ Color-coded by priority (red=emergency, orange=warnings, etc.)
- ✅ Easy to scan visually
- ✅ Can be opened in any web browser

**Use when:**
- Need quick visual reference
- Want color-coded priority indicators
- Training new operators
- Creating presentations or documentation
- Prefer visual organization

**Color Coding:**
- 🔴 **Red** - Emergency (Kill Switch, Critical Alerts)
- 🟠 **Orange** - Warnings (Alerts, Monitoring)
- 🔵 **Blue** - Status & Information
- 🟢 **Green** - Success, Snapshots, Metrics
- 🟣 **Purple** - Filters & Configuration

## 📋 What's Covered

Both versions include comprehensive coverage of:

### 🚨 Emergency Kill Switch
- Activation methods (CLI, API, File System)
- Status checking
- When to activate
- Deactivation procedures

### 📊 Status Commands
- Account & balance status
- Trading system diagnostics
- Analytics & reports
- Profit status checks

### 🔔 Alerts & Monitoring
- Critical alert thresholds
- Auto kill-switch triggers
- Safety tests
- Monitoring integration

### 📸 Snapshots & Metrics
- Command Center 8 key metrics
- API endpoints for real-time data
- Performance snapshots
- Programmatic access

### 🔍 Market Filters
- Filter thresholds (ADX, volume, spread, etc.)
- Market quality checks
- Python integration examples
- Default values

### 🎯 Operational Quick Actions
- Start/stop commands
- Environment configuration
- Trade veto reasons
- Common troubleshooting

### 📈 Analytics Tracking
- 11 entry reason types
- 19 exit reason types
- Signal type classification
- Data file locations

### 🐛 Troubleshooting
- Bot won't start
- No trades executing
- Heartbeat failures
- API issues

### ⚡ Rapid Fire Commands
- Quick health checks
- Real-time monitoring
- Log viewing
- Safety test execution

## 🚀 Quick Start

### View Markdown Version
```bash
# In terminal
cat NIJA_OPERATOR_QUICK_REFERENCE.md

# Or open in editor
nano NIJA_OPERATOR_QUICK_REFERENCE.md
code NIJA_OPERATOR_QUICK_REFERENCE.md
```

### View HTML Version
```bash
# Open in default browser (macOS)
open NIJA_OPERATOR_QUICK_REFERENCE.html

# Open in default browser (Linux)
xdg-open NIJA_OPERATOR_QUICK_REFERENCE.html

# Open in default browser (Windows)
start NIJA_OPERATOR_QUICK_REFERENCE.html

# Or simply double-click the file in your file explorer
```

### Print to PDF

**From Markdown:**
```bash
# Using pandoc
pandoc NIJA_OPERATOR_QUICK_REFERENCE.md -o NIJA_Quick_Reference.pdf

# Using grip (GitHub-flavored markdown)
grip NIJA_OPERATOR_QUICK_REFERENCE.md --export NIJA_Quick_Reference.html
```

**From HTML:**
- Open in browser → Print → Save as PDF
- Use browser's "Print to PDF" feature
- Professional quality with colors and icons preserved

## 📖 Related Documentation

The Quick Reference Cards consolidate information from:

- `EMERGENCY_KILL_SWITCH_QUICK_REF.md` - Kill switch procedures
- `QUICK_REFERENCE.md` - Railway deployment & features
- `ANALYTICS_QUICK_REFERENCE.md` - Analytics commands
- `COMMAND_CENTER_README.md` - Dashboard metrics
- `OPERATIONAL_SAFETY_PROCEDURES.md` - Safety protocols
- `README.md` - Main project documentation

## 🎯 Target Audience

- **NIJA Operators** - Day-to-day bot operation
- **On-Call Engineers** - Emergency response
- **System Administrators** - Health monitoring
- **New Team Members** - Quick onboarding
- **DevOps Engineers** - Deployment & troubleshooting

## ⏱️ Target Response Times

The Quick Reference is designed to help operators achieve:

- **Emergency Kill Switch:** < 30 seconds (actual: < 5 seconds via CLI)
- **Status Check:** < 1 minute
- **Health Assessment:** < 2 minutes
- **Troubleshooting:** < 5 minutes to identify issue

## 💡 Best Practices

1. **Keep accessible:** Bookmark HTML version or keep terminal with markdown open
2. **Print physical copy:** For emergency situations without computer access
3. **Review regularly:** Familiarize yourself with commands before emergencies
4. **Update bookmarks:** Add key API endpoints to browser bookmarks
5. **Test commands:** Try emergency procedures in test environment first
6. **Share with team:** Ensure all operators have access to both versions

## 🔄 Updates

These Quick Reference Cards are current as of **Version 7.2.0** (February 2026).

When NIJA is updated:
- Check for new commands in release notes
- Update both markdown and HTML versions
- Test all commands still work
- Verify API endpoints are current
- Update version numbers

## 📝 Customization

### Markdown Version
- Edit directly in any text editor
- Add your own sections or commands
- Adjust for your specific deployment

### HTML Version
- CSS variables at top of file for easy color changes
- Modify color scheme by editing `:root` CSS variables
- Add/remove sections by editing HTML structure
- Responsive design works on all screen sizes

## 🆘 Emergency Contact

In case of critical emergency:

1. **Activate kill switch FIRST** - Don't investigate while bot is still trading
2. **Review logs** - `tail -f logs/nija.log`
3. **Check positions** - Via broker UI (Kraken/Coinbase)
4. **Follow procedures** - In `OPERATIONAL_SAFETY_PROCEDURES.md`
5. **Document incident** - For post-mortem analysis

## ✅ Verification Checklist

Before relying on Quick Reference in production:

- [ ] Verify all commands work in your environment
- [ ] Test kill switch activation/deactivation
- [ ] Confirm API endpoints are accessible
- [ ] Test status commands return expected data
- [ ] Verify file paths match your installation
- [ ] Bookmark HTML version for quick access
- [ ] Print physical copy for backup
- [ ] Train team on emergency procedures

---

**Last Updated:** February 2026  
**Version:** 7.2.0  
**Status:** Production Ready ✅
