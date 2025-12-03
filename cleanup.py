#!/usr/bin/env python3
"""
Production Cleanup Script - Moves non-essential files to archive/
"""
import os
import shutil
from pathlib import Path

ROOT = Path("/workspaces/Nija")
ARCHIVE = ROOT / "archive"

# Essential files to KEEP
ESSENTIAL = {
    # Core bot
    "bot/", 
    # Deployment
    "Dockerfile", "start.sh", "requirements.txt", "railway.json", "runtime.txt",
    # Documentation
    "README.md", ".env.example",
    # Git
    ".git/", ".gitignore", ".dockerignore", ".github/",
    # Optional dev
    ".vscode/", ".devcontainer/",
    # Archive itself
    "archive/",
    # This cleanup script
    "cleanup.py", "cleanup_production.sh", ".cleanignore"
}

def should_keep(path: Path) -> bool:
    """Check if file/folder should be kept"""
    rel_path = path.relative_to(ROOT)
    str_path = str(rel_path)
    
    # Check exact matches
    if str_path in ESSENTIAL:
        return True
    
    # Check if in essential directory
    for essential in ESSENTIAL:
        if essential.endswith('/') and str_path.startswith(essential):
            return True
    
    return False

def main():
    print("🧹 NIJA Production Cleanup")
    print("=" * 50)
    
    os.chdir(ROOT)
    
    # Get all items in root
    items = list(ROOT.iterdir())
    
    moved = []
    kept = []
    
    for item in items:
        if item.name.startswith('.') and item.name not in ['.gitignore', '.dockerignore', '.env.example', '.cleanignore']:
            # Skip hidden files except essential ones
            continue
            
        if should_keep(item):
            kept.append(item.name)
            continue
        
        # Determine archive destination
        name = item.name
        
        if 'test' in name.lower() or 'check' in name.lower() or 'debug' in name.lower():
            dest = ARCHIVE / "test_files" / name
        elif name.endswith('.sh'):
            dest = ARCHIVE / "build_scripts" / name
        elif name.endswith('.whl'):
            dest = ARCHIVE / "wheel_files" / name
        elif name.endswith(('.patch', '.diff', '.toml', '.yml', '.yaml')) or 'Dockerfile.' in name:
            dest = ARCHIVE / "old_configs" / name
        else:
            dest = ARCHIVE / "test_files" / name
        
        # Move to archive
        try:
            if item.is_dir():
                shutil.move(str(item), str(dest))
            else:
                shutil.move(str(item), str(dest))
            moved.append(name)
            print(f"📦 {name}")
        except Exception as e:
            print(f"⚠️  Error moving {name}: {e}")
    
    print("\n" + "=" * 50)
    print(f"✅ Moved {len(moved)} items to archive/")
    print(f"📌 Kept {len(kept)} essential items")
    
    print("\n📁 Production Structure:")
    print("\nbot/")
    if (ROOT / "bot").exists():
        for f in sorted((ROOT / "bot").iterdir()):
            print(f"  - {f.name}")
    
    print("\nRoot files:")
    for item in sorted(ROOT.iterdir()):
        if item.is_file() and not item.name.startswith('.'):
            print(f"  - {item.name}")

if __name__ == "__main__":
    main()
