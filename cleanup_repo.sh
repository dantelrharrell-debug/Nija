#!/bin/bash
# NIJA Repo Cleanup - Remove unnecessary files

echo "🧹 Cleaning up NIJA repository..."

# Remove test files (not in bot/)
find . -type f -name "*test*.py" ! -path "./bot/*" ! -path "./.git/*" -delete

# Remove debug files
find . -type f -name "*debug*.py" ! -path "./bot/*" ! -path "./.git/*" -delete

# Remove check/verify files
find . -type f -name "*check*.py" ! -path "./bot/*" ! -path "./.git/*" -delete
find . -type f -name "*verify*.py" ! -path "./bot/*" ! -path "./.git/*" -delete
find . -type f -name "*diagnose*.py" ! -path "./bot/*" ! -path "./.git/*" -delete

# Remove wheel files
find . -type f -name "*.whl" -delete

# Remove patch files
find . -type f -name "*.patch" -delete
find . -type f -name "*.diff" -delete

# Remove old build scripts
rm -f build_*.sh
rm -f ci_*.sh
rm -f add_*.sh
rm -f commit_*.sh
rm -f fix_*.sh
rm -f cleanup_*.sh
rm -f clone_*.sh
rm -f deploy.sh.save
rm -f rollback_*.sh

# Remove duplicate/old app files
rm -rf app/ src/ web_service/ bot_service/ opt/

# Remove old PEM files (keep only .env)
find . -type f -name "*.pem" ! -name ".env" -delete

# Remove unnecessary docs
rm -f *.txt
rm -f *.md ! -name "README.md"

# Remove old python scripts in root
rm -f nija_*.py
rm -f coinbase_*.py
rm -f start_*.py
rm -f bot.py bot_live.py
rm -f app.py web_app.py wsgi.py
rm -f data_fetcher.py
rm -f balance_helper.py
rm -f config.py
rm -f position_manager.py
rm -f trading_logic.py
rm -f example_usage.py
rm -f get-pip.py
rm -f __init__.py

# Remove old dockerfiles
rm -f Dockerfile.bot Dockerfile.patch Dockerfile.web

echo "✅ Cleanup complete!"
echo ""
echo "Kept:"
echo "  - bot/ (NIJA trading logic)"
echo "  - .env (credentials)"
echo "  - Dockerfile (main)"
echo "  - railway.json"
echo "  - deploy_to_railway.sh"
echo "  - requirements.txt"
