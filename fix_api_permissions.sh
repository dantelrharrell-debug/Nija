#!/bin/bash
# API Key Permission Fix Guide

cat << 'EOF'

================================================================================
🔧 FIX COINBASE API PERMISSIONS - GET ACCESS TO YOUR $156.97
================================================================================

PROBLEM: Your API keys can't see the funds in Advanced Trade portfolio
CAUSE:   Missing "Portfolio Management" or "All Portfolios" permission

SOLUTION: Create new API keys with correct permissions


================================================================================
📋 STEP-BY-STEP INSTRUCTIONS
================================================================================

1. Open this URL in your browser:
   https://www.coinbase.com/settings/api

2. Click the "New API Key" button

3. Select "Cloud API Trading Keys" (NOT Legacy keys)

4. Enable THESE EXACT PERMISSIONS:
   ☑️  View
   ☑️  Trade  
   ☑️  Transfer
   ☑️  Portfolio Management  ← CRITICAL!
   
5. Under "Portfolio Access":
   ☑️  Select "All portfolios"  ← MUST SELECT THIS!
   
   OR specifically select:
   ☑️  Default
   ☑️  Nija

6. Give it a name like "NIJA Bot - Full Access"

7. Click "Create & Download"

8. IMPORTANT: Save the downloaded file somewhere safe!

9. From the downloaded JSON file, copy:
   - "keyId" → This is your COINBASE_API_KEY
   - "privateKey" → This is your COINBASE_API_SECRET (PEM format)


================================================================================
🔄 AFTER CREATING THE NEW KEY
================================================================================

Option 1 - Use the update script:
   1. Edit the file: quick_update_keys.py
   2. Replace NEW_API_KEY with your new key
   3. Replace NEW_API_SECRET with your new PEM key
   4. Run: python3 quick_update_keys.py

Option 2 - Manual .env edit:
   1. Open .env file
   2. Replace COINBASE_API_KEY=...
   3. Replace COINBASE_API_SECRET=...
   4. Save and run: python3 find_my_157.py


================================================================================
✅ VERIFY IT WORKS
================================================================================

Run this command to test:
   python3 find_my_157.py

You should see:
   💰 Advanced Trade USD Total: $156.97
   🎯 FOUND YOUR $157.97!


================================================================================
⚠️  IMPORTANT SECURITY NOTES
================================================================================

• NEVER commit .env file to git (it's in .gitignore)
• Keep your PEM private key secure
• Don't share API keys in screenshots or messages
• If keys are compromised, immediately delete them in Coinbase settings


================================================================================

EOF

echo ""
echo "Press ENTER when you've created the new API keys with proper permissions..."
read

echo ""
echo "Do you want to update the keys now? (y/n)"
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Opening quick_update_keys.py for editing..."
    echo "Update the NEW_API_KEY and NEW_API_SECRET variables, then save and run:"
    echo "  python3 quick_update_keys.py"
    echo ""
    
    # Open the file in the default editor
    ${EDITOR:-nano} quick_update_keys.py
else
    echo ""
    echo "No problem! When ready, edit quick_update_keys.py and run:"
    echo "  python3 quick_update_keys.py"
    echo ""
fi
