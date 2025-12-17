#!/bin/bash

# Simple file-based verification
OUTPUT_FILE="/tmp/git_verify.txt"

{
    echo "=========================================="
    echo "GIT STATUS"
    echo "=========================================="
    git status --short
    echo ""
    
    echo "=========================================="
    echo "LAST 3 COMMITS"
    echo "=========================================="
    git log --oneline -3
    echo ""
    
    echo "=========================================="
    echo "LAST COMMIT FULL DETAILS"
    echo "=========================================="
    git log -1
    echo ""
    
    echo "=========================================="
    echo "FILES IN LAST COMMIT"
    echo "=========================================="
    git show --stat HEAD
    
} > "$OUTPUT_FILE"

cat "$OUTPUT_FILE"
echo ""
echo "✅ Output also saved to: $OUTPUT_FILE"
