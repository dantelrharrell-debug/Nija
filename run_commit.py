#!/usr/bin/env python3
"""
Execute the commit_filter_changes.sh script to push filter relaxation changes
"""
import subprocess
import sys
import os

def main():
    os.chdir('/workspaces/Nija')
    
    # Make script executable
    subprocess.run(['chmod', '+x', 'commit_filter_changes.sh'], check=True)
    
    # Run the script
    result = subprocess.run(['bash', 'commit_filter_changes.sh'], 
                          capture_output=True, 
                          text=True)
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    sys.exit(result.returncode)

if __name__ == '__main__':
    main()
