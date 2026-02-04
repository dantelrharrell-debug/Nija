#!/usr/bin/env python3
"""
Pre-commit hook to prevent breaking database schema changes without migrations.

This hook scans staged files for database schema changes and ensures that
corresponding Alembic migrations exist.

Author: NIJA Trading Systems
Date: February 4, 2026
"""

import re
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple


# Patterns that indicate schema changes
SCHEMA_CHANGE_PATTERNS = [
    # SQLAlchemy model changes
    (r'class\s+\w+\(.*Base.*\):', 'New database model class'),
    (r'__tablename__\s*=', 'Table name definition'),
    (r'Column\s*\(', 'Column definition'),
    (r'ForeignKey\s*\(', 'Foreign key definition'),
    (r'Index\s*\(', 'Index definition'),
    (r'UniqueConstraint\s*\(', 'Unique constraint definition'),
    
    # Direct SQL operations (should be in migrations)
    (r'CREATE\s+TABLE', 'CREATE TABLE statement'),
    (r'DROP\s+TABLE', 'DROP TABLE statement'),
    (r'ALTER\s+TABLE', 'ALTER TABLE statement'),
    (r'ADD\s+COLUMN', 'ADD COLUMN statement'),
    (r'DROP\s+COLUMN', 'DROP COLUMN statement'),
]

# Files to check
MODEL_PATTERNS = [
    'database/models/*.py',
    'bot/*models*.py',
    'auth/models.py',
]

# Files to exclude
EXCLUDE_PATTERNS = [
    'alembic/versions/*.py',  # Migration files are OK
    'test_*.py',  # Test files are OK
    '*/test_*.py',
]


def get_staged_files() -> List[str]:
    """Get list of staged Python files"""
    try:
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'],
            capture_output=True,
            text=True,
            check=True
        )
        files = [f for f in result.stdout.strip().split('\n') if f.endswith('.py')]
        return files
    except subprocess.CalledProcessError:
        return []


def should_check_file(filepath: str) -> bool:
    """Determine if file should be checked for schema changes"""
    # Exclude certain patterns
    for pattern in EXCLUDE_PATTERNS:
        if Path(filepath).match(pattern):
            return False
    
    # Check if it's a model file or in database directory
    if 'model' in filepath.lower() or 'database' in filepath.lower():
        return True
    
    return False


def check_file_for_schema_changes(filepath: str) -> List[Tuple[int, str, str]]:
    """
    Check file for schema changes.
    
    Returns:
        List of (line_number, pattern_description, line_content)
    """
    issues = []
    
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        for i, line in enumerate(lines, 1):
            for pattern, description in SCHEMA_CHANGE_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append((i, description, line.strip()))
        
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)
    
    return issues


def check_recent_migrations() -> bool:
    """Check if there are recent migration files"""
    migrations_dir = Path('alembic/versions')
    
    if not migrations_dir.exists():
        return False
    
    # Get list of migration files
    migration_files = list(migrations_dir.glob('*.py'))
    migration_files = [f for f in migration_files if f.name != '__init__.py']
    
    if not migration_files:
        return False
    
    # Check if any migrations are staged
    staged_files = get_staged_files()
    staged_migrations = [f for f in staged_files if 'alembic/versions' in f]
    
    return len(staged_migrations) > 0


def main():
    """Main hook logic"""
    print("🔍 Checking for database schema changes...")
    
    staged_files = get_staged_files()
    if not staged_files:
        print("✅ No staged files to check")
        return 0
    
    # Check each staged file
    schema_changes_found = False
    files_with_changes = []
    
    for filepath in staged_files:
        if not should_check_file(filepath):
            continue
        
        issues = check_file_for_schema_changes(filepath)
        if issues:
            schema_changes_found = True
            files_with_changes.append((filepath, issues))
    
    if not schema_changes_found:
        print("✅ No schema changes detected")
        return 0
    
    # Schema changes found - check for migration
    print("\n⚠️  DATABASE SCHEMA CHANGES DETECTED\n")
    
    for filepath, issues in files_with_changes:
        print(f"📄 {filepath}:")
        for line_num, description, line_content in issues[:3]:  # Show first 3
            print(f"   Line {line_num}: {description}")
            print(f"   → {line_content}")
        if len(issues) > 3:
            print(f"   ... and {len(issues) - 3} more")
        print()
    
    # Check if migration exists
    if check_recent_migrations():
        print("✅ Migration file found in staged changes")
        print("📝 Proceeding with commit\n")
        return 0
    
    # No migration found
    print("❌ SCHEMA FREEZE VIOLATION")
    print("=" * 70)
    print("Database schema changes require an Alembic migration.")
    print()
    print("To fix this issue:")
    print()
    print("1. Create a migration:")
    print("   alembic revision -m 'describe your change'")
    print()
    print("2. Edit the migration file in alembic/versions/")
    print("   - Implement upgrade() function")
    print("   - Implement downgrade() function")
    print()
    print("3. Test the migration:")
    print("   alembic upgrade head")
    print("   alembic downgrade -1")
    print()
    print("4. Stage the migration file:")
    print("   git add alembic/versions/<your_migration>.py")
    print()
    print("5. Retry your commit")
    print()
    print("📖 See DATABASE_MIGRATION_POLICY.md for details")
    print("=" * 70)
    print()
    print("To bypass this check (NOT RECOMMENDED):")
    print("   git commit --no-verify")
    print()
    
    return 1


if __name__ == '__main__':
    sys.exit(main())
