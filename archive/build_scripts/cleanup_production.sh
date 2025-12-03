#!/bin/bash
set -e

echo "🧹 NIJA Production Cleanup Script"
echo "=================================="
echo ""
echo "This will:"
echo "  1. Archive all test/debug files to archive/"
echo "  2. Delete unnecessary files"
echo "  3. Keep only production-essential files"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    exit 1
fi

# Create archive directory
mkdir -p archive/test_files
mkdir -p archive/debug_files
mkdir -p archive/old_configs
mkdir -p archive/build_scripts
mkdir -p archive/wheel_files

echo "📦 Moving test files to archive..."
mv *test*.py archive/test_files/ 2>/dev/null || true
mv check_*.py archive/test_files/ 2>/dev/null || true
mv debug_*.py archive/test_files/ 2>/dev/null || true
mv validate_*.py archive/test_files/ 2>/dev/null || true
mv verify_*.py archive/test_files/ 2>/dev/null || true
mv inspect_*.py archive/test_files/ 2>/dev/null || true
mv diagnose_*.py archive/test_files/ 2>/dev/null || true
mv auto_*.py archive/test_files/ 2>/dev/null || true
mv fetch_*.py archive/test_files/ 2>/dev/null || true
mv list_*.py archive/test_files/ 2>/dev/null || true

echo "🗑️  Moving old config/scripts to archive..."
mv *.patch archive/old_configs/ 2>/dev/null || true
mv *.diff archive/old_configs/ 2>/dev/null || true
mv build_*.sh archive/build_scripts/ 2>/dev/null || true
mv deploy_*.sh archive/build_scripts/ 2>/dev/null || true
mv setup_*.sh archive/build_scripts/ 2>/dev/null || true
mv *_deps.sh archive/build_scripts/ 2>/dev/null || true
mv cleanup_*.sh archive/build_scripts/ 2>/dev/null || true
mv ci_*.sh archive/build_scripts/ 2>/dev/null || true
mv clone_*.sh archive/build_scripts/ 2>/dev/null || true
mv commit_*.sh archive/build_scripts/ 2>/dev/null || true
mv rebase_*.sh archive/build_scripts/ 2>/dev/null || true
mv release_*.sh archive/build_scripts/ 2>/dev/null || true
mv rollback_*.sh archive/build_scripts/ 2>/dev/null || true
mv railway_*.sh archive/build_scripts/ 2>/dev/null || true

echo "💾 Moving wheel files to archive..."
mv *.whl archive/wheel_files/ 2>/dev/null || true

echo "🗂️  Moving old Python files to archive..."
mv nija_*.py archive/test_files/ 2>/dev/null || true
mv coinbase_*.py archive/test_files/ 2>/dev/null || true
mv cdp_*.py archive/test_files/ 2>/dev/null || true
mv jwt_*.py archive/test_files/ 2>/dev/null || true
mv pem_*.py archive/test_files/ 2>/dev/null || true
mv generate_*.py archive/test_files/ 2>/dev/null || true
mv extract_*.py archive/test_files/ 2>/dev/null || true
mv convert_*.py archive/test_files/ 2>/dev/null || true
mv fix_*.py archive/test_files/ 2>/dev/null || true
mv safe_*.py archive/test_files/ 2>/dev/null || true
mv place_*.py archive/test_files/ 2>/dev/null || true

echo "🧹 Cleaning up old directories..."
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

echo "🗑️  Deleting obsolete files..."
rm -f =*.0 2>/dev/null || true
rm -f BOT_ROOT EMA 2>/dev/null || true
rm -f .deploy.sh.swp 2>/dev/null || true
rm -f "cd ~/" "tash push -m backup before sync" 2>/dev/null || true
rm -f test_coinbase_connection 2>/dev/null || true
rm -f *.txt.bak 2>/dev/null || true
rm -f .high-frequency-update .railway-trigger 2>/dev/null || true
rm -f coinbase.pem mykey.pem coinbase_secret.txt 2>/dev/null || true

echo "📋 Moving old docs to archive..."
mv README.old archive/old_configs/ 2>/dev/null || true
mv IMPLEMENTATION_SUMMARY.md archive/old_configs/ 2>/dev/null || true
mv SAFE_TRADING_STACK.md archive/old_configs/ 2>/dev/null || true
mv deploy-checklist.md archive/old_configs/ 2>/dev/null || true

echo "🧹 Moving unused Dockerfiles..."
mv Dockerfile.bot archive/old_configs/ 2>/dev/null || true
mv Dockerfile.patch archive/old_configs/ 2>/dev/null || true
mv Dockerfile.web archive/old_configs/ 2>/dev/null || true
mv docker-compose.yml archive/old_configs/ 2>/dev/null || true

echo "🗂️  Moving old config files..."
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

echo "🗑️  Moving old entry point files..."
mv entrypoint.sh archive/old_configs/ 2>/dev/null || true
mv entrypoint_check.py archive/old_configs/ 2>/dev/null || true
mv healthcheck.py archive/old_configs/ 2>/dev/null || true
mv pre_start.py archive/old_configs/ 2>/dev/null || true
mv startup.py archive/old_configs/ 2>/dev/null || true
mv startup_env.py archive/old_configs/ 2>/dev/null || true
mv get-pip.py archive/old_configs/ 2>/dev/null || true

echo "🗂️  Moving old root-level Python files..."
mv app.py archive/test_files/ 2>/dev/null || true
mv bot.py archive/test_files/ 2>/dev/null || true
mv bot_live.py archive/test_files/ 2>/dev/null || true
mv live_bot.py archive/test_files/ 2>/dev/null || true
mv live_check.py archive/test_files/ 2>/dev/null || true
mv live_monitor.py archive/test_files/ 2>/dev/null || true
mv balance_helper.py archive/test_files/ 2>/dev/null || true
mv config.py archive/test_files/ 2>/dev/null || true
mv data_fetcher.py archive/test_files/ 2>/dev/null || true
mv example_usage.py archive/test_files/ 2>/dev/null || true
mv import_check.py archive/test_files/ 2>/dev/null || true
mv indicators.py archive/test_files/ 2>/dev/null || true
mv position_manager.py archive/test_files/ 2>/dev/null || true
mv signals.py archive/test_files/ 2>/dev/null || true
mv trading_engine.py archive/test_files/ 2>/dev/null || true
mv trading_logic.py archive/test_files/ 2>/dev/null || true
mv tradingview_webhook.py archive/test_files/ 2>/dev/null || true
mv tv_webhook_listener.py archive/test_files/ 2>/dev/null || true
mv ultimate_nija_ai.py archive/test_files/ 2>/dev/null || true
mv web.py archive/test_files/ 2>/dev/null || true
mv web_app.py archive/test_files/ 2>/dev/null || true
mv web_service.py archive/test_files/ 2>/dev/null || true
mv wsgi.py archive/test_files/ 2>/dev/null || true
mv venv_inspect.py archive/test_files/ 2>/dev/null || true
mv start_*.py archive/test_files/ 2>/dev/null || true
mv start_*.sh archive/test_files/ 2>/dev/null || true
mv confirm_*.py archive/test_files/ 2>/dev/null || true
mv enable_*.py archive/test_files/ 2>/dev/null || true
mv try_*.py archive/test_files/ 2>/dev/null || true

echo "🗑️  Moving misc files..."
mv pip_list.txt archive/test_files/ 2>/dev/null || true
mv pip_show_coinbase.txt archive/test_files/ 2>/dev/null || true
mv import_test.txt archive/test_files/ 2>/dev/null || true
mv local.env archive/old_configs/ 2>/dev/null || true
mv .gitmodules archive/old_configs/ 2>/dev/null || true
mv deploy.sh.save archive/build_scripts/ 2>/dev/null || true
mv install_pylance.sh archive/build_scripts/ 2>/dev/null || true
mv nija_tester.sh archive/build_scripts/ 2>/dev/null || true
mv deploy.sh archive/build_scripts/ 2>/dev/null || true

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "📁 Production structure:"
tree -L 2 -I 'archive|__pycache__|.git' .

echo ""
echo "📦 Archived files are in ./archive/"
echo "💡 To permanently delete archive: rm -rf archive/"
