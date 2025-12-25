#!/usr/bin/env python3
import subprocess
import sys
import os

os.chdir('/workspaces/Nija')

try:
    # Stage all files
    print("📝 Staging all changes...")
    subprocess.run(['git', 'add', '-A'], check=True)
    
    # Check status
    print("\n📋 Git status:")
    result = subprocess.run(['git', 'status', '--short'], capture_output=True, text=True)
    print(result.stdout)
    
    # Commit if there are changes
    if result.stdout.strip():
        print("\n💾 Committing changes...")
        subprocess.run([
            'git', 'commit', '-m',
            'chore: update deployment status and redeploy scripts'
        ], check=True)
        
        # Push
        print("\n🚀 Pushing to origin/main...")
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        
        print("\n✅ Successfully committed and pushed all changes!")
    else:
        print("\n✅ No changes to commit")
    
    sys.exit(0)
    
except subprocess.CalledProcessError as e:
    print(f"\n❌ Git command failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ Error: {e}")
    sys.exit(1)
