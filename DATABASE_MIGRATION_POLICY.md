# Database Schema Migration Policy

## Overview

This policy defines the procedures and requirements for database schema changes in the NIJA trading platform. It ensures safe, reversible migrations without breaking changes or data loss.

**Status**: ACTIVE - Schema changes are frozen and require migration scripts  
**Last Updated**: February 4, 2026  
**Effective Date**: February 4, 2026

---

## Core Principles

1. **No Direct Schema Changes**: All schema changes MUST go through the Alembic migration system
2. **Backward Compatibility**: New migrations MUST NOT break existing code
3. **Reversibility**: All migrations MUST be reversible (include downgrade logic)
4. **Data Safety**: Never delete columns or tables without explicit backup
5. **Testing Required**: All migrations MUST be tested before production deployment

---

## Schema Freeze Policy

### What is Frozen

The following operations are PROHIBITED without a proper migration:

- ❌ Adding new tables directly in code
- ❌ Dropping existing tables
- ❌ Renaming tables or columns
- ❌ Changing column types
- ❌ Adding/removing constraints (NOT NULL, FOREIGN KEY, UNIQUE)
- ❌ Changing column defaults
- ❌ Adding/removing indexes

### Exceptions

The following operations are allowed WITHOUT migration (they don't change schema):

- ✅ Inserting/updating/deleting data
- ✅ Changing application logic
- ✅ Adding new Python models (without creating tables)
- ✅ Updating queries or ORM relationships

---

## Migration Process

### Step 1: Plan the Change

Before creating a migration:

1. Document the reason for the schema change
2. Identify all affected tables, columns, and relationships
3. Consider backward compatibility implications
4. Plan the rollback strategy
5. Estimate migration time for large datasets

### Step 2: Create Migration Script

```bash
# Generate new migration
alembic revision -m "descriptive_message_about_change"

# Example:
alembic revision -m "add_user_risk_profile_table"
alembic revision -m "add_order_timeout_column"
alembic revision -m "create_index_on_trades_timestamp"
```

This creates a new file in `alembic/versions/` with:
- `upgrade()`: Apply the schema change
- `downgrade()`: Reverse the schema change

### Step 3: Implement Migration

Edit the generated migration file:

```python
"""Add user risk profile table

Revision ID: abc123def456
Create Date: 2026-02-04 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# Revision identifiers
revision = 'abc123def456'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade():
    """Apply the schema change"""
    op.create_table(
        'user_risk_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(50), nullable=False),
        sa.Column('risk_level', sa.String(20), nullable=False),
        sa.Column('max_position_size', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )
    
    # Create index for performance
    op.create_index('ix_risk_profiles_user_id', 'user_risk_profiles', ['user_id'])


def downgrade():
    """Reverse the schema change"""
    op.drop_index('ix_risk_profiles_user_id', table_name='user_risk_profiles')
    op.drop_table('user_risk_profiles')
```

### Step 4: Test Migration

```bash
# Test upgrade
alembic upgrade head

# Verify schema changes
# ... check database ...

# Test downgrade
alembic downgrade -1

# Verify rollback worked
# ... check database ...

# Re-apply if tests pass
alembic upgrade head
```

### Step 5: Update Application Code

Update Python models, queries, and application logic to work with the new schema.

**IMPORTANT**: Code changes should be backward compatible with the old schema until migration is deployed.

### Step 6: Deploy

1. **Backup database** before deployment
2. Apply migration in staging environment first
3. Verify application works correctly
4. Apply migration in production during maintenance window
5. Monitor for errors

---

## Migration Guidelines

### Adding Columns

**Allowed** with migration:

```python
def upgrade():
    op.add_column('trades', sa.Column('slippage_pct', sa.Float(), nullable=True))
    
def downgrade():
    op.drop_column('trades', 'slippage_pct')
```

**Best Practices**:
- New columns should be nullable OR have default values
- Don't add NOT NULL columns without default
- Consider adding in two steps: (1) nullable column, (2) populate data, (3) add NOT NULL

### Dropping Columns

**Dangerous** - requires careful planning:

```python
def upgrade():
    # Step 1: Backup data if needed
    # Step 2: Remove column
    op.drop_column('trades', 'old_unused_field')
    
def downgrade():
    # Restore column structure (data will be lost!)
    op.add_column('trades', sa.Column('old_unused_field', sa.String(100), nullable=True))
```

**Before dropping**:
1. Ensure column is truly unused (search codebase)
2. Backup data if it might be needed
3. Wait at least 1 release cycle before dropping
4. Consider archiving data instead of deleting

### Renaming Columns

**Risky** - use carefully:

```python
def upgrade():
    op.alter_column('trades', 'old_name', new_column_name='new_name')
    
def downgrade():
    op.alter_column('trades', 'new_name', new_column_name='old_name')
```

**Alternative approach** (safer):
1. Add new column with new name
2. Copy data from old column to new column
3. Deploy code changes to use new column
4. After verification, drop old column

### Changing Column Types

**High Risk** - test thoroughly:

```python
def upgrade():
    # May require data conversion
    op.alter_column('trades', 'amount',
                    existing_type=sa.Integer(),
                    type_=sa.Float(),
                    postgresql_using='amount::float')
    
def downgrade():
    # May lose precision
    op.alter_column('trades', 'amount',
                    existing_type=sa.Float(),
                    type_=sa.Integer(),
                    postgresql_using='amount::integer')
```

**Considerations**:
- Data loss risk (e.g., float → integer)
- Performance impact on large tables
- Application compatibility

---

## Migration Checklist

Before deploying a migration, ensure:

- [ ] Migration script includes both `upgrade()` and `downgrade()`
- [ ] Migration tested in local environment
- [ ] Migration tested in staging environment
- [ ] Downgrade tested (can reverse the change)
- [ ] Database backup created
- [ ] Migration time estimated for production data volume
- [ ] Application code updated to handle both old and new schema (if needed)
- [ ] Documentation updated (README, API docs, etc.)
- [ ] Team notified of schema change
- [ ] Rollback plan documented

---

## Emergency Rollback

If a migration causes issues:

```bash
# Rollback to previous version
alembic downgrade -1

# Rollback to specific version
alembic downgrade abc123def456

# Rollback all migrations (DANGEROUS)
alembic downgrade base
```

**Post-rollback**:
1. Investigate the issue
2. Fix the migration script
3. Test thoroughly
4. Retry deployment

---

## Monitoring Migrations

After deploying a migration:

1. Check application logs for database errors
2. Monitor query performance
3. Verify data integrity
4. Check for lock contention (long-running migrations)
5. Monitor disk space (new indexes, columns)

---

## Common Mistakes to Avoid

1. ❌ **Not testing downgrade**: Always test reversibility
2. ❌ **Breaking changes**: Don't drop columns/tables without deprecation period
3. ❌ **Missing defaults**: Adding NOT NULL columns without defaults
4. ❌ **Large table migrations**: Not considering impact on production
5. ❌ **No backup**: Running migrations without database backup
6. ❌ **Deploying code before migration**: Code expects new schema but it's not deployed yet

---

## Pre-Commit Hook

A pre-commit hook checks for schema changes in code without corresponding migrations.

**Location**: `.pre-commit-hooks/check-schema-changes.py`

The hook prevents:
- Direct table creation in models without migration
- Schema changes without Alembic revision
- Breaking changes without proper migration

---

## Questions?

For schema change questions or migration help:

1. Review this policy
2. Check existing migrations in `alembic/versions/`
3. Test in local/staging environment first
4. Ask for peer review before production deployment

---

## Version History

- **v1.0** (2026-02-04): Initial schema freeze policy
