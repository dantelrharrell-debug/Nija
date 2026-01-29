#!/usr/bin/env python3
"""
NIJA Database Initialization Script

This script initializes the PostgreSQL database for the NIJA trading platform.
It creates all necessary tables and initial data.

Usage:
    python init_database.py [--drop-all]
    
Options:
    --drop-all    Drop all existing tables before recreating (DESTRUCTIVE)
"""

import sys
import os
import logging
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from database.models import Base, User, UserPermission
from database.db_connection import (
    init_database,
    get_engine,
    get_session,
    close_database,
    test_connection,
    get_database_url
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def drop_all_tables():
    """Drop all tables (DESTRUCTIVE)"""
    logger.warning("⚠️  DROPPING ALL TABLES...")
    engine = get_engine()
    Base.metadata.drop_all(engine)
    logger.info("✅ All tables dropped")


def create_all_tables():
    """Create all tables defined in models"""
    logger.info("Creating all tables...")
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("✅ All tables created successfully")


def create_demo_user():
    """Create a demo user for testing"""
    session = get_session()
    
    try:
        # Check if demo user exists
        existing_user = session.query(User).filter_by(email='demo@nija.ai').first()
        
        if existing_user:
            logger.info("Demo user already exists")
            return
        
        # Create demo user
        demo_user = User(
            user_id='user_demo',
            email='demo@nija.ai',
            password_hash='$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYzpLaEg7.C',  # demo password: "demo123"
            subscription_tier='pro',
            enabled=True
        )
        session.add(demo_user)
        
        # Create permissions for demo user
        demo_permissions = UserPermission(
            user_id='user_demo',
            max_position_size_usd=1000.00,
            max_daily_loss_usd=500.00,
            max_positions=10,
            trade_only=True,
            enabled=True
        )
        session.add(demo_permissions)
        
        session.commit()
        logger.info("✅ Demo user created: demo@nija.ai / demo123")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create demo user: {e}")
        raise
    finally:
        session.close()


def verify_database():
    """Verify database setup"""
    logger.info("Verifying database setup...")
    session = get_session()
    
    try:
        # Count tables
        from sqlalchemy import inspect
        engine = get_engine()
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        logger.info(f"✅ Found {len(tables)} tables:")
        for table in sorted(tables):
            logger.info(f"   - {table}")
        
        # Count users
        user_count = session.query(User).count()
        logger.info(f"✅ Total users: {user_count}")
        
        return True
        
    except Exception as e:
        logger.error(f"Database verification failed: {e}")
        return False
    finally:
        session.close()


def main():
    """Main initialization function"""
    parser = argparse.ArgumentParser(description='Initialize NIJA database')
    parser.add_argument(
        '--drop-all',
        action='store_true',
        help='Drop all existing tables before recreating (DESTRUCTIVE)'
    )
    parser.add_argument(
        '--demo-user',
        action='store_true',
        help='Create demo user for testing'
    )
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("🚀 NIJA Database Initialization")
    logger.info("=" * 60)
    
    # Get database URL (without displaying password)
    db_url = get_database_url()
    safe_url = db_url.split('@')[1] if '@' in db_url else db_url
    logger.info(f"Database: {safe_url}")
    
    try:
        # Initialize database connection
        logger.info("Initializing database connection...")
        init_database(pool_size=5, max_overflow=10)
        
        # Test connection
        if not test_connection():
            logger.error("❌ Database connection failed")
            return 1
        
        # Drop all tables if requested
        if args.drop_all:
            if input("Are you sure you want to drop all tables? (yes/no): ").lower() != 'yes':
                logger.info("Aborted")
                return 0
            drop_all_tables()
        
        # Create all tables
        create_all_tables()
        
        # Create demo user if requested
        if args.demo_user:
            create_demo_user()
        
        # Verify database
        if verify_database():
            logger.info("=" * 60)
            logger.info("✅ Database initialization complete!")
            logger.info("=" * 60)
            return 0
        else:
            logger.error("❌ Database verification failed")
            return 1
            
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        close_database()


if __name__ == '__main__':
    sys.exit(main())
