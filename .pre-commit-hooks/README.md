# Pre-Commit Hooks

This directory contains custom pre-commit hooks for the NIJA trading bot.

## Available Hooks

### check-terminology.sh

Prevents regressions of the terminology migration by checking for prohibited hierarchical terms in log statements.

**Purpose:** Ensure neutral, non-hierarchical language is maintained throughout the codebase.

**What it checks:**
- Scans Python files for prohibited patterns in logger statements
- Enforces neutral terminology guidelines
- Prevents accidental reintroduction of hierarchical language

**Prohibited terms:**
- "master" (use "platform" instead)
- "controls users/accounts"
- "under control/coordination"
- "primary platform/broker"
- "leads accounts/users"
- "generate signal"
- "receive trade"
- "simultaneously with"

**Allowed exceptions:**
- `hard controls` (safety system module)
- `master_event`, `master_signal` (test variables)
- `follower_pnl` (technical module)
- Files in `archive/` directory
- Test files (`test_*.py`)
- Diagnostic scripts (`diagnose_*.py`)

**Usage:**
```bash
# Automatic: Runs on every commit
git commit -m "Your message"

# Manual: Run on all files
.pre-commit-hooks/check-terminology.sh

# Via pre-commit
pre-commit run check-terminology --all-files
```

**Output:**
- ✅ Success: No prohibited terms found
- ❌ Failure: Shows violations with line numbers and suggested alternatives

## Installation

See `.pre-commit-config.yaml` for hook configuration.

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Test all hooks
pre-commit run --all-files
```

## Adding New Hooks

1. Create a new shell script in this directory
2. Make it executable: `chmod +x hook-name.sh`
3. Add configuration to `.pre-commit-config.yaml`
4. Test the hook: `pre-commit run hook-name --all-files`
5. Document it in this README

## Troubleshooting

**Hook not running:**
- Check if pre-commit is installed: `pre-commit --version`
- Verify hooks are installed: `ls .git/hooks/pre-commit`
- Reinstall hooks: `pre-commit install`

**False positives:**
- Update `ALLOWED_EXCEPTIONS` in the script
- Or exclude specific files in `.pre-commit-config.yaml`

**Need to bypass:**
```bash
# Emergency only - use with caution
git commit --no-verify -m "Your message"
```

## Contributing

When adding new hooks:
- Keep them fast (< 1 second for typical commits)
- Provide clear error messages with solutions
- Add proper exclusions for test/archive files
- Document in this README
- Test on CI before merging
