#!/bin/bash
# Simple cleanup - move everything except essentials to archive

cd /workspaces/Nija

echo "Moving test files..."
find . -maxdepth 1 -name "*test*.py" -exec mv {} archive/test_files/ \;
find . -maxdepth 1 -name "test_*.py" -exec mv {} archive/test_files/ \;

echo "Moving check files..."
find . -maxdepth 1 -name "check_*.py" -exec mv {} archive/test_files/ \;
find . -maxdepth 1 -name "*check*.py" -exec mv {} archive/test_files/ \;

echo "Moving debug files..."
find . -maxdepth 1 -name "debug_*.py" -exec mv {} archive/test_files/ \;
find . -maxdepth 1 -name "*debug*.py" -exec mv {} archive/test_files/ \;

echo "Moving nija_ variant files..."
find . -maxdepth 1 -name "nija_*.py" -exec mv {} archive/test_files/ \;

echo "Moving coinbase_ variant files..."
find . -maxdepth 1 -name "coinbase_*.py" -exec mv {} archive/test_files/ \;

echo "Moving other Python files..."
mv validate_*.py archive/test_files/ 2>/dev/null || true
mv verify_*.py archive/test_files/ 2>/dev/null || true
mv inspect_*.py archive/test_files/ 2>/dev/null || true
mv diagnose_*.py archive/test_files/ 2>/dev/null || true
mv fetch_*.py archive/test_files/ 2>/dev/null || true
mv generate_*.py archive/test_files/ 2>/dev/null || true
mv extract_*.py archive/test_files/ 2>/dev/null || true
mv convert_*.py archive/test_files/ 2>/dev/null || true
mv decode_*.py archive/test_files/ 2>/dev/null || true
mv fix_*.py archive/test_files/ 2>/dev/null || true
mv list_*.py archive/test_files/ 2>/dev/null || true
mv jwt_*.py archive/test_files/ 2>/dev/null || true
mv pem_*.py archive/test_files/ 2>/dev/null || true
mv cdp_*.py archive/test_files/ 2>/dev/null || true
mv auto_*.py archive/test_files/ 2>/dev/null || true
mv place_*.py archive/test_files/ 2>/dev/null || true
mv safe_*.py archive/test_files/ 2>/dev/null || true
mv try_*.py archive/test_files/ 2>/dev/null || true
mv enable_*.py archive/test_files/ 2>/dev/null || true
mv confirm_*.py archive/test_files/ 2>/dev/null || true
mv start_*.py archive/test_files/ 2>/dev/null || true
mv pre_*.py archive/test_files/ 2>/dev/null || true
mv startup*.py archive/test_files/ 2>/dev/null || true
mv entrypoint*.py archive/test_files/ 2>/dev/null || true
mv healthcheck.py archive/test_files/ 2>/dev/null || true
mv venv_*.py archive/test_files/ 2>/dev/null || true
mv preflight_*.py archive/test_files/ 2>/dev/null || true

# Old standalone files
mv app.py archive/test_files/ 2>/dev/null || true
mv bot.py archive/test_files/ 2>/dev/null || true  
mv bot_live.py archive/test_files/ 2>/dev/null || true
mv live_*.py archive/test_files/ 2>/dev/null || true
mv web.py archive/test_files/ 2>/dev/null || true
mv web_app.py archive/test_files/ 2>/dev/null || true
mv web_service.py archive/test_files/ 2>/dev/null || true
mv wsgi.py archive/test_files/ 2>/dev/null || true
mv trading_*.py archive/test_files/ 2>/dev/null || true
mv tradingview_*.py archive/test_files/ 2>/dev/null || true
mv tv_*.py archive/test_files/ 2>/dev/null || true
mv ultimate_*.py archive/test_files/ 2>/dev/null || true
mv balance_*.py archive/test_files/ 2>/dev/null || true
mv config.py archive/test_files/ 2>/dev/null || true
mv data_fetcher.py archive/test_files/ 2>/dev/null || true
mv example_*.py archive/test_files/ 2>/dev/null || true
mv import_*.py archive/test_files/ 2>/dev/null || true
mv indicators.py archive/test_files/ 2>/dev/null || true
mv position_*.py archive/test_files/ 2>/dev/null || true
mv signals.py archive/test_files/ 2>/dev/null || true
mv __init__.py archive/test_files/ 2>/dev/null || true

echo "Moving build scripts..."
mv *.sh archive/build_scripts/ 2>/dev/null || true
# Keep start.sh
mv archive/build_scripts/start.sh . 2>/dev/null || true

echo "Moving wheel files..."
mv *.whl archive/wheel_files/ 2>/dev/null || true

echo "Moving patch/diff files..."
mv *.patch archive/old_configs/ 2>/dev/null || true
mv *.diff archive/old_configs/ 2>/dev/null || true

echo "Moving old configs..."
mv Dockerfile.* archive/old_configs/ 2>/dev/null || true
mv docker-compose.yml archive/old_configs/ 2>/dev/null || true
mv Procfile archive/old_configs/ 2>/dev/null || true
mv fly.toml archive/old_configs/ 2>/dev/null || true
mv render.yaml archive/old_configs/ 2>/dev/null || true
mv gunicorn.conf.py archive/old_configs/ 2>/dev/null || true
mv pyproject.toml archive/old_configs/ 2>/dev/null || true
mv setup.py archive/old_configs/ 2>/dev/null || true
mv constraints.txt archive/old_configs/ 2>/dev/null || true
mv requirements-dev.txt archive/old_configs/ 2>/dev/null || true
mv requirements.web.txt archive/old_configs/ 2>/dev/null || true
mv requirements.bot.txt archive/old_configs/ 2>/dev/null || true
mv requirements.txt.bak archive/old_configs/ 2>/dev/null || true
mv local.env archive/old_configs/ 2>/dev/null || true
mv .gitmodules archive/old_configs/ 2>/dev/null || true

echo "Moving old directories..."
mv app/ archive/ 2>/dev/null || true
mv bot_service/ archive/ 2>/dev/null || true
mv bots/ archive/ 2>/dev/null || true
mv cd/ archive/ 2>/dev/null || true
mv docs/ archive/ 2>/dev/null || true
mv github/ archive/ 2>/dev/null || true
mv nija-trading-bot/ archive/ 2>/dev/null || true
mv nija_bundle/ archive/ 2>/dev/null || true
mv opt/ archive/ 2>/dev/null || true
mv project-root/ archive/ 2>/dev/null || true
mv scripts/ archive/ 2>/dev/null || true
mv src/ archive/ 2>/dev/null || true
mv tests/ archive/ 2>/dev/null || true
mv web/ archive/ 2>/dev/null || true
mv web_service/ archive/ 2>/dev/null || true
mv devcontainer/ archive/ 2>/dev/null || true

echo "Moving old docs..."
mv README.old archive/old_configs/ 2>/dev/null || true
mv IMPLEMENTATION_SUMMARY.md archive/old_configs/ 2>/dev/null || true
mv SAFE_TRADING_STACK.md archive/old_configs/ 2>/dev/null || true
mv deploy-checklist.md archive/old_configs/ 2>/dev/null || true

echo "Moving secrets..."
mv coinbase.pem archive/ 2>/dev/null || true
mv mykey.pem archive/ 2>/dev/null || true
mv coinbase_secret.txt archive/ 2>/dev/null || true

echo "Moving junk files..."
mv "=1.26.0" archive/ 2>/dev/null || true
mv "=2.1.0" archive/ 2>/dev/null || true
mv "=2.31.0" archive/ 2>/dev/null || true
mv "=2.6.0" archive/ 2>/dev/null || true
mv "=46.0.0" archive/ 2>/dev/null || true
mv BOT_ROOT archive/ 2>/dev/null || true
mv EMA archive/ 2>/dev/null || true
mv "cd ~/" archive/ 2>/dev/null || true
mv "tash push -m backup before sync" archive/ 2>/dev/null || true
mv test_coinbase_connection archive/ 2>/dev/null || true
mv pip_list.txt archive/ 2>/dev/null || true
mv pip_show_coinbase.txt archive/ 2>/dev/null || true
mv import_test.txt archive/ 2>/dev/null || true
mv .deploy.sh.swp archive/ 2>/dev/null || true
mv .high-frequency-update archive/ 2>/dev/null || true
mv .railway-trigger archive/ 2>/dev/null || true
mv .cleanignore archive/ 2>/dev/null || true
mv cleanup.py archive/ 2>/dev/null || true
mv cleanup_production.sh archive/ 2>/dev/null || true
mv get-pip.py archive/ 2>/dev/null || true
mv test_import.py.save archive/ 2>/dev/null || true
mv deploy.sh.save archive/ 2>/dev/null || true

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Production structure:"
ls -1
