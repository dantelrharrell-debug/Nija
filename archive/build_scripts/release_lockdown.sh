#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="your-org-or-username"   # <--- edit this
REPO_NAME="Nija"                    # <--- edit this if repo is different

echo "1) Ensure you're on main and up to date"
git checkout main
git pull origin main

echo
echo "2) Update poetry lock & install dependencies (bot/)"
cd bot
poetry lock
poetry install --no-root --no-dev
cd ..

echo
echo "3) Build docker image locally to verify"
docker build -t nija:staging .

echo
echo "4) Run container locally (optional smoke test)"
echo "   (Ctrl-C to stop after you test endpoints)"
docker run --rm -p 5000:5000 --env LIVE_TRADING=0 nija:staging &

echo
echo "Test health endpoint:"
echo "  curl http://localhost:5000/health"
read -p "Press ENTER after you verify the health endpoint (or Ctrl-C to abort)..."

# kill background container (if left running)
pkill -f "docker run --rm -p 5000:5000 --env LIVE_TRADING=0 nija:staging" || true

echo
echo "5) Prepare GitHub Secrets and branch protection (gh CLI required)"
read -p "Do you want to set GitHub secrets now? [y/N] " setsecrets
if [[ "${setsecrets:-N}" =~ ^[Yy]$ ]]; then
  read -p "Enter production environment name (ex: production) or press ENTER for repo secrets: " ENVNAME
  echo "Enter value for TV_WEBHOOK_SECRET (will be saved):"
  read -s TV_SECRET
  echo
  echo "Enter value for COINBASE_API_KEY (will be saved):"
  read -s CB_KEY
  echo
  echo "Enter value for COINBASE_API_SECRET (will be saved):"
  read -s CB_SECRET
  echo
  echo "Enter value for COINBASE_API_SUB (will be saved):"
  read -s CB_SUB

  if [[ -z "$ENVNAME" ]]; then
    echo "Saving secrets at repo-level..."
    gh secret set TV_WEBHOOK_SECRET --body "$TV_SECRET" --repo "$REPO_OWNER/$REPO_NAME"
    gh secret set COINBASE_API_KEY --body "$CB_KEY" --repo "$REPO_OWNER/$REPO_NAME"
    gh secret set COINBASE_API_SECRET --body "$CB_SECRET" --repo "$REPO_OWNER/$REPO_NAME"
    gh secret set COINBASE_API_SUB --body "$CB_SUB" --repo "$REPO_OWNER/$REPO_NAME"
    gh secret set LIVE_TRADING --body "0" --repo "$REPO_OWNER/$REPO_NAME"
  else
    echo "Saving secrets to GitHub environment: $ENVNAME"
    # create environment if not exists
    gh api -X POST /repos/"$REPO_OWNER"/"$REPO_NAME"/environments -f name="$ENVNAME" || true
    gh secret set TV_WEBHOOK_SECRET --body "$TV_SECRET" --env "$ENVNAME" --repo "$REPO_OWNER/$REPO_NAME"
    gh secret set COINBASE_API_KEY --body "$CB_KEY" --env "$ENVNAME" --repo "$REPO_OWNER/$REPO_NAME"
    gh secret set COINBASE_API_SECRET --body "$CB_SECRET" --env "$ENVNAME" --repo "$REPO_OWNER/$REPO_NAME"
    gh secret set COINBASE_API_SUB --body "$CB_SUB" --env "$ENVNAME" --repo "$REPO_OWNER/$REPO_NAME"
    gh secret set LIVE_TRADING --body "0" --env "$ENVNAME" --repo "$REPO_OWNER/$REPO_NAME"
  fi
fi

echo
read -p "Apply branch protection to main now (requires repo admin)? [y/N] " protect
if [[ "${protect:-N}" =~ ^[Yy]$ ]]; then
  echo "Applying branch protection: require PR reviews and status checks"
  gh api --method PUT \
    /repos/"$REPO_OWNER"/"$REPO_NAME"/branches/main/protection \
    -f required_status_checks.strict=true \
    -f required_status_checks.contexts='["CI — Prebuild checks & poetry install"]' \
    -f enforce_admins=true \
    -f required_pull_request_reviews.dismiss_stale_reviews=false \
    -f required_pull_request_reviews.require_code_owner_reviews=false \
    -f restrictions='null'
  echo "Branch protection API call complete."
fi

echo
echo "Finished. Next recommended steps:"
echo " - Verify GitHub Actions CI runs on your next PR."
echo " - Keep LIVE_TRADING=0 in prod until staging verified."
echo " - When ready to enable live trading: set LIVE_TRADING=1 in production env and monitor carefully."
