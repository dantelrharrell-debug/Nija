#!/bin/bash
# Pre-commit hook to prevent hierarchical terminology regressions
# Checks for prohibited terms in log statements

set -e

# Color codes for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Prohibited patterns (case-insensitive)
# These should not appear in logger statements
PROHIBITED_PATTERNS=(
    # Hierarchical terms
    'logger\.(info|warning|error|debug|critical).*[Mm]aster'
    'logger\.(info|warning|error|debug|critical).*controls\s+(user|account)'
    'logger\.(info|warning|error|debug|critical).*under\s+(control|coordination)'
    'logger\.(info|warning|error|debug|critical).*primary\s+(platform|broker)'
    'logger\.(info|warning|error|debug|critical).*lead(s|ing)?\s+(account|user)'
    'logger\.(info|warning|error|debug|critical).*follower'
    
    # Specific prohibited phrases
    'logger\.(info|warning|error|debug|critical).*generate.*signal'
    'logger\.(info|warning|error|debug|critical).*receive.*trade'
    'logger\.(info|warning|error|debug|critical).*simultaneously\s+with'
)

# Allowed exceptions (these patterns are OK)
ALLOWED_EXCEPTIONS=(
    'hard controls'  # Safety system module
    'master_event'   # Variable name in tests
    'master_signal'  # Variable name in tests
    'is_master'      # Variable/property name
    'follower_pnl'   # Technical module for follower profit tracking
    'MASTER_FOLLOW'  # Legacy config value (deprecated)
)

# Files to check (Python files only)
FILES_TO_CHECK=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)

if [ -z "$FILES_TO_CHECK" ]; then
    # No Python files changed
    exit 0
fi

VIOLATIONS_FOUND=0
VIOLATION_DETAILS=""

# Check each file
for file in $FILES_TO_CHECK; do
    if [ ! -f "$file" ]; then
        continue
    fi
    
    # Skip test files and diagnostic scripts (they may reference old terminology)
    if [[ "$file" == test_* ]] || [[ "$file" == diagnose_* ]] || [[ "$file" == **/test_* ]] || [[ "$file" == archive/* ]]; then
        continue
    fi
    
    # Get the staged content
    STAGED_CONTENT=$(git show ":$file")
    
    # Check each prohibited pattern
    for pattern in "${PROHIBITED_PATTERNS[@]}"; do
        # Search for pattern in file
        MATCHES=$(echo "$STAGED_CONTENT" | grep -n -E "$pattern" || true)
        
        if [ -n "$MATCHES" ]; then
            # Check if it's an allowed exception
            IS_ALLOWED=0
            for exception in "${ALLOWED_EXCEPTIONS[@]}"; do
                # Use word boundaries to avoid false positives
                if echo "$MATCHES" | grep -qiE "\b${exception}\b"; then
                    IS_ALLOWED=1
                    break
                fi
            done
            
            if [ $IS_ALLOWED -eq 0 ]; then
                VIOLATIONS_FOUND=1
                VIOLATION_DETAILS="${VIOLATION_DETAILS}\n${YELLOW}File: $file${NC}\n"
                VIOLATION_DETAILS="${VIOLATION_DETAILS}${RED}Pattern: $pattern${NC}\n"
                VIOLATION_DETAILS="${VIOLATION_DETAILS}$MATCHES\n"
            fi
        fi
    done
done

# Report results
if [ $VIOLATIONS_FOUND -eq 1 ]; then
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}❌ TERMINOLOGY CHECK FAILED${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e ""
    echo -e "Prohibited hierarchical terminology detected in log statements:"
    echo -e "$VIOLATION_DETAILS"
    echo -e ""
    echo -e "${YELLOW}Prohibited terms:${NC}"
    echo -e "  ❌ 'master' (use 'platform' instead)"
    echo -e "  ❌ 'controls users/accounts' (use 'account group loaded' instead)"
    echo -e "  ❌ 'under control/coordination' (use 'trading independently' instead)"
    echo -e "  ❌ 'primary platform/broker' (use 'active broker' instead)"
    echo -e "  ❌ 'leads accounts/users'"
    echo -e "  ❌ 'generate signal' (use 'trading independently' instead)"
    echo -e "  ❌ 'receive trade' (use 'trading independently' instead)"
    echo -e "  ❌ 'simultaneously with'"
    echo -e ""
    echo -e "${YELLOW}Allowed neutral phrases:${NC}"
    echo -e "  ✅ 'platform account initialized'"
    echo -e "  ✅ 'independent account group initialized'"
    echo -e "  ✅ 'platform + user accounts trading independently'"
    echo -e "  ✅ 'account registered for independent execution'"
    echo -e "  ✅ 'account group loaded (no trade copying)'"
    echo -e "  ✅ 'active broker'"
    echo -e "  ✅ 'trading independently'"
    echo -e ""
    echo -e "${YELLOW}For more information, see: TERMINOLOGY_MIGRATION.md${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 1
fi

# Success
echo "✅ Terminology check passed - no prohibited terms found"
exit 0
