# NIJA Production Repository - Cleanup Summary

## Current State
The repository contains 200+ files from development/debugging, including:
- 80+ test/debug/check Python files
- 40+ old nija_/coinbase_ variant files  
- 20+ build/deployment scripts
- 10+ .whl packages
- Multiple duplicate Dockerfiles
- Old directories (app/, bots/, web/, tests/, etc.)

## Essential Production Files (KEEP)
```
bot/
├── __init__.py
├── live_trading.py
├── trading_strategy.py
├── indicators.py
├── nija_trailing_system.py
└── market_adapter.py

Dockerfile
start.sh
requirements.txt
railway.json
runtime.txt
README.md
.env.example
.gitignore
.dockerignore
.git/
.github/
```

## Cleanup Script Created
`do_cleanup.sh` - Moves all non-essential files to archive/

## To Execute Cleanup
Run from terminal:
```bash
cd /workspaces/Nija
bash do_cleanup.sh
```

## Post-Cleanup Expected Structure
```
/workspaces/Nija/
├── bot/                    # Core bot directory  
│   ├── __init__.py
│   ├── live_trading.py
│   ├── trading_strategy.py
│   ├── indicators.py
│   ├── nija_trailing_system.py
│   └── market_adapter.py
├── archive/                # All archived files
│   ├── test_files/         # Test/debug/check files
│   ├── build_scripts/      # Build scripts
│   ├── wheel_files/        # .whl packages
│   └── old_configs/        # Old configs
├── .git/
├── .gitignore
├── .dockerignore
├── .env
├── .env.example
├── .github/
├── Dockerfile
├── start.sh
├── requirements.txt
├── railway.json
├── runtime.txt
└── README.md
```

## After Cleanup - Git Commit
```bash
git add -A
git commit -m "Production cleanup - archived dev files, kept essentials only"
git push origin main
```

## Archive Can Be Deleted Later
Once confirmed working:
```bash
rm -rf archive/
git add -A  
git commit -m "Removed archive after verification"
git push
```
