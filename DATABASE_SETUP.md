# NIJA Database Setup Guide

This guide explains how to set up and manage the PostgreSQL database for the NIJA trading platform.

## Prerequisites

- PostgreSQL 14+ installed
- Python 3.11+ with required packages (see requirements.txt)
- Environment variables configured

## Quick Start

### 1. Environment Variables

Create a `.env` file with your PostgreSQL credentials:

```bash
# PostgreSQL Connection
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=nija
POSTGRES_USER=nija_user
POSTGRES_PASSWORD=your_secure_password

# Or use a single DATABASE_URL (for cloud deployments)
DATABASE_URL=postgresql://nija_user:password@localhost:5432/nija
```

### 2. Create PostgreSQL Database

```bash
# Login to PostgreSQL
psql -U postgres

# Create database and user
CREATE DATABASE nija;
CREATE USER nija_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE nija TO nija_user;

# Exit psql
\q
```

### 3. Initialize Database

```bash
# Initialize database schema
python init_database.py

# Or with demo user for testing
python init_database.py --demo-user
```

This will create all necessary tables:
- `users` - User accounts
- `broker_credentials` - Encrypted API credentials
- `user_permissions` - Trading limits and permissions
- `trading_instances` - Bot instances
- `positions` - Active trading positions
- `trades` - Trade history
- `daily_statistics` - Daily aggregated stats

### 4. Verify Setup

```python
from database.db_connection import init_database, test_connection

# Initialize connection
init_database()

# Test connection
if test_connection():
    print("✅ Database connected!")
```

## Database Migrations with Alembic

### Generate Migration

When you modify database models, create a migration:

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Add new field to User model"
```

### Apply Migrations

```bash
# Run all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history

# View current version
alembic current
```

### Manual Migration

```bash
# Create empty migration
alembic revision -m "Custom migration"

# Edit the generated file in alembic/versions/
# Implement upgrade() and downgrade() functions
```

## Database Schema

### Users Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key (auto-increment) |
| user_id | String(50) | Unique user identifier |
| email | String(255) | User email (unique) |
| password_hash | String(255) | Hashed password (Argon2) |
| subscription_tier | String(20) | basic/pro/enterprise |
| enabled | Boolean | Account status |
| created_at | DateTime | Registration timestamp |
| updated_at | DateTime | Last update timestamp |

### Broker Credentials Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| user_id | String(50) | Foreign key to users |
| broker_name | String(50) | Broker name (coinbase, kraken, etc.) |
| encrypted_api_key | Text | Encrypted API key |
| encrypted_api_secret | Text | Encrypted API secret |
| encrypted_additional_params | Text | Additional broker-specific params |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

### Positions Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| user_id | String(50) | Foreign key to users |
| pair | String(20) | Trading pair (BTC-USD) |
| side | String(10) | long/short |
| size | Numeric(18,8) | Position size |
| entry_price | Numeric(18,8) | Entry price |
| current_price | Numeric(18,8) | Current market price |
| pnl | Numeric(18,8) | Profit/Loss in USD |
| pnl_percent | Numeric(8,4) | P&L percentage |
| opened_at | DateTime | Position open time |
| closed_at | DateTime | Position close time (null if open) |
| status | String(20) | open/closed |

### Trades Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| user_id | String(50) | Foreign key to users |
| pair | String(20) | Trading pair |
| side | String(10) | buy/sell |
| size | Numeric(18,8) | Trade size |
| entry_price | Numeric(18,8) | Entry price |
| exit_price | Numeric(18,8) | Exit price |
| pnl | Numeric(18,8) | Realized P&L |
| pnl_percent | Numeric(8,4) | P&L percentage |
| fees | Numeric(18,8) | Trading fees |
| opened_at | DateTime | Trade open time |
| closed_at | DateTime | Trade close time |
| status | String(20) | open/closed |

## Connection Pooling

The database uses SQLAlchemy's connection pooling for optimal performance:

```python
from database.db_connection import init_database

# Initialize with custom pool settings
init_database(
    pool_size=10,        # Number of connections to keep in pool
    max_overflow=20,     # Maximum overflow connections
    pool_timeout=30,     # Timeout for getting connection (seconds)
    pool_recycle=3600    # Recycle connections after 1 hour
)
```

### Pool Monitoring

```python
from database.db_connection import get_pool_status

# Get current pool status
status = get_pool_status()
print(f"Pool size: {status['size']}")
print(f"Checked out: {status['checked_out']}")
print(f"Checked in: {status['checked_in']}")
print(f"Overflow: {status['overflow']}")
```

## Health Checks

```python
from database.db_connection import check_database_health

# Check database health
health = check_database_health()

if health['healthy']:
    print("✅ Database is healthy")
    print(f"Pool status: {health['pool']}")
else:
    print(f"❌ Database unhealthy: {health['error']}")
```

## Best Practices

### 1. Use Context Managers

Always use context managers for database sessions:

```python
from database.db_connection import get_db_session
from database.models import User

# Automatic commit/rollback
with get_db_session() as session:
    user = session.query(User).filter_by(email='user@example.com').first()
    # Session automatically commits on success, rolls back on error
```

### 2. Close Connections

Always close database connections when done:

```python
from database.db_connection import close_database

# At application shutdown
close_database()
```

### 3. Index Usage

Ensure queries use indexes for performance:

```sql
-- Check query plan
EXPLAIN ANALYZE SELECT * FROM trades WHERE user_id = 'user_123';

-- Should use index: ix_trades_user_id
```

### 4. Regular Backups

```bash
# Backup database
pg_dump -U nija_user -d nija > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from backup
psql -U nija_user -d nija < backup_20260129_131500.sql
```

## Troubleshooting

### Connection Refused

```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql

# Start PostgreSQL
sudo systemctl start postgresql
```

### Permission Denied

```sql
-- Grant permissions to user
GRANT ALL PRIVILEGES ON DATABASE nija TO nija_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO nija_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO nija_user;
```

### Migration Conflicts

```bash
# Check current migration version
alembic current

# View history
alembic history

# Force to specific version (careful!)
alembic stamp head
```

## Production Deployment

### Cloud PostgreSQL

For production, use managed PostgreSQL services:

- **Railway**: Automatic PostgreSQL provisioning
- **Heroku Postgres**: Managed PostgreSQL with backups
- **AWS RDS**: Scalable managed database
- **Google Cloud SQL**: Enterprise-grade database

### Security Checklist

- [ ] Use strong passwords (16+ characters)
- [ ] Enable SSL connections
- [ ] Restrict network access (firewall rules)
- [ ] Regular automated backups
- [ ] Monitor connection pool usage
- [ ] Set up alerts for errors
- [ ] Enable query logging (temporarily for debugging)
- [ ] Use read replicas for analytics queries

### Performance Optimization

1. **Indexes**: Ensure all foreign keys and frequently queried columns are indexed
2. **Connection Pooling**: Tune pool size based on load (10-20 for most apps)
3. **Query Optimization**: Use `EXPLAIN ANALYZE` to optimize slow queries
4. **Vacuum**: Run `VACUUM ANALYZE` regularly on high-churn tables
5. **Partitioning**: Partition large tables (e.g., trades by month)

## Support

For issues or questions:
1. Check logs: `tail -f /var/log/postgresql/postgresql-14-main.log`
2. Review migration history: `alembic history`
3. Verify environment variables are set
4. Test connection: `psql -U nija_user -d nija`

---

**Document Version**: 1.0
**Last Updated**: January 29, 2026
**Status**: Production Ready
