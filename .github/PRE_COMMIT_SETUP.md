# Pre-Commit Secret Scanning Setup

## Overview

NIJA uses pre-commit hooks to prevent secrets from being committed to the repository. This is a critical security layer that catches issues before they reach GitHub.

## Installation

### 1. Install Pre-Commit

```bash
# Using pip
pip install pre-commit

# Using homebrew (macOS)
brew install pre-commit

# Using apt (Ubuntu/Debian)
sudo apt install pre-commit
```

### 2. Install Git Hooks

After cloning the repository:

```bash
cd /path/to/Nija
pre-commit install
```

This installs the git hook scripts in `.git/hooks/`. Now `pre-commit` will run automatically on `git commit`.

### 3. (Optional) Install Commit-Msg Hook

```bash
pre-commit install --hook-type commit-msg
```

## Usage

### Automatic Checks on Commit

Once installed, pre-commit hooks run automatically:

```bash
git add .
git commit -m "Your commit message"

# Pre-commit hooks will run automatically
# If any check fails, the commit will be blocked
```

### Manual Checks

Run all hooks on all files:

```bash
pre-commit run --all-files
```

Run a specific hook:

```bash
pre-commit run detect-secrets --all-files
pre-commit run gitleaks --all-files
pre-commit run bandit --all-files
```

Run hooks on specific files:

```bash
pre-commit run --files bot/trading_strategy.py
```

### Bypass Hooks (Emergency Only)

**⚠️ WARNING**: Only use in emergencies, never to bypass security checks!

```bash
git commit --no-verify -m "Emergency commit"
```

## Installed Hooks

### Secret Detection

1. **detect-secrets** (Yelp)
   - Fast, baseline-driven secret detection
   - Uses `.secrets.baseline` for known false positives
   - Scans for API keys, tokens, passwords

2. **gitleaks**
   - Comprehensive secret scanner
   - Uses `.gitleaks.toml` for configuration
   - Industry-standard tool used by many organizations

3. **trufflehog**
   - Advanced pattern matching
   - Only reports verified secrets
   - Reduces false positives

4. **detect-private-key**
   - Catches SSH/PEM private keys
   - Prevents accidental certificate commits

5. **detect-aws-credentials**
   - AWS-specific credential detection
   - Catches AWS access keys and secrets

### Custom NIJA Checks

1. **check-env-files**
   - Blocks commits of `.env` file (use `.env.example` instead)
   - Protects against most common secret leak

2. **check-api-keys**
   - Pattern matching for hardcoded API keys
   - Catches Coinbase, Kraken, Alpaca credentials

3. **check-pem-files**
   - Blocks commits of `.pem`, `.key`, `.crt` files
   - Prevents certificate leaks

### Code Quality

1. **bandit**
   - Python security linting
   - Catches common security issues in code
   - Configuration: `.bandit.yml`

2. **Standard pre-commit hooks**
   - Trailing whitespace removal
   - End-of-file fixing
   - YAML/JSON syntax checking
   - Large file detection (>5MB)
   - Merge conflict detection
   - Python AST validation

## Handling False Positives

### detect-secrets

If a legitimate file is flagged as containing secrets:

1. Audit the file to ensure it's NOT a real secret
2. Add to baseline:

```bash
detect-secrets scan --baseline .secrets.baseline
git add .secrets.baseline
git commit -m "Update secrets baseline"
```

### gitleaks

Add patterns to `.gitleaks.toml` allowlist:

```toml
[allowlist]
paths = [
  '''path/to/file.py''',
]

regexes = [
  '''pattern-to-ignore''',
]
```

## Best Practices

### ✅ DO

- Install pre-commit hooks immediately after cloning
- Run `pre-commit run --all-files` before pushing
- Update hooks regularly: `pre-commit autoupdate`
- Report false positives so they can be baselined
- Review what hooks caught before bypassing

### ❌ DON'T

- Use `--no-verify` to bypass hooks without good reason
- Commit real secrets (even if you plan to remove later)
- Ignore hook failures without investigating
- Remove security hooks to "speed up" commits
- Share `.env` files containing real credentials

## Troubleshooting

### Hooks running slowly

Some hooks (especially full repository scans) can be slow on first run. Subsequent runs are faster due to caching.

```bash
# Skip slow hooks during development (but run before push!)
SKIP=trufflehog,gitleaks git commit -m "WIP: development commit"

# Always run all hooks before pushing
pre-commit run --all-files
git push
```

### Hook installation fails

```bash
# Clear cache and reinstall
pre-commit clean
pre-commit install --install-hooks
```

### Secrets detected in old commits

Pre-commit only scans new commits. Old secrets in history require:

```bash
# Scan entire git history with gitleaks
gitleaks detect --source . --verbose

# Or with trufflehog
trufflehog git file://. --only-verified
```

If secrets found in history, see: [GitHub Docs - Removing Sensitive Data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

### Skip specific hook temporarily

```bash
SKIP=hook-name git commit -m "Message"
```

Example:
```bash
SKIP=bandit git commit -m "WIP: refactoring security check"
```

## CI Integration

Pre-commit hooks also run in CI via `.github/workflows/security-scan.yml`. This ensures:

- Developers can't bypass hooks by using `--no-verify`
- All pull requests are scanned before merge
- Scheduled scans catch drift and new vulnerabilities

## Updating Hooks

Keep hooks up to date:

```bash
# Update to latest hook versions
pre-commit autoupdate

# Commit the updated configuration
git add .pre-commit-config.yaml
git commit -m "Update pre-commit hooks"
```

## Additional Resources

- [pre-commit documentation](https://pre-commit.com/)
- [detect-secrets](https://github.com/Yelp/detect-secrets)
- [gitleaks](https://github.com/gitleaks/gitleaks)
- [trufflehog](https://github.com/trufflesecurity/trufflehog)
- [NIJA Security Documentation](SECURITY.md)

## Support

If you encounter issues:

1. Check the troubleshooting section above
2. Review hook output for specific errors
3. Consult `.pre-commit-config.yaml` configuration
4. Open an issue with details of the problem

---

**Remember**: Pre-commit hooks are your first line of defense. They're there to protect you and the project. Don't bypass them unless absolutely necessary!
