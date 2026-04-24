"""
NIJA Database Connection Module

Manages PostgreSQL database connections and provides utilities for
connection pooling, health checks, and session management.

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
import os
from typing import Optional, Dict, Any
from contextlib import contextmanager
from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# Global engine and session maker
_engine: Optional[Any] = None
_session_factory: Optional[sessionmaker] = None
_scoped_session: Optional[scoped_session] = None


def get_database_url() -> str:
    """
    Get database URL from environment variables

    Returns:
        PostgreSQL connection URL

    Raises:
        ValueError: If password is missing from credentials
    """
    # Try DATABASE_URL first (common for cloud platforms)
    db_url = os.getenv('DATABASE_URL')

    if not db_url:
        # Build from individual components
        db_host = os.getenv('POSTGRES_HOST', 'localhost')
        db_port = os.getenv('POSTGRES_PORT', '5432')
        db_name = os.getenv('POSTGRES_DB', 'nija')
        db_user = os.getenv('POSTGRES_USER', 'nija_user')
        db_password = os.getenv('POSTGRES_PASSWORD')

        if not db_password:
            raise ValueError(
                "POSTGRES_PASSWORD environment variable is required for database connection. "
                "Please set POSTGRES_PASSWORD or provide a complete DATABASE_URL with credentials."
            )

        db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    else:
        # Validate that DATABASE_URL contains a password
        # Format: postgresql://user:password@host:port/database
        # Check for empty password (e.g., user:@host or user@host)
        if '://' in db_url:
            # Extract the credentials portion between :// and @
            try:
                scheme_and_rest = db_url.split('://', 1)
                if len(scheme_and_rest) == 2:
                    rest = scheme_and_rest[1]
                    if '@' in rest:
                        credentials = rest.split('@', 1)[0]
                        # Check if password is present (format: user:password)
                        if ':' in credentials:
                            password = credentials.split(':', 1)[1]
                            if not password:
                                raise ValueError(
                                    "DATABASE_URL contains empty password. "
                                    "Database connections must include valid credentials for security."
                                )
                        else:
                            # No password separator found
                            raise ValueError(
                                "DATABASE_URL missing password. "
                                "Format must be: postgresql://user:password@host:port/database"
                            )
            except (IndexError, ValueError) as e:
                if "DATABASE_URL" in str(e):
                    raise
                # Re-raise with more context if it's a parsing error
                raise ValueError(
                    f"Invalid DATABASE_URL format. Expected: postgresql://user:password@host:port/database"
                ) from e

    # Handle postgres:// prefix (some platforms use this instead of postgresql://)
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    return db_url


def init_database(
    database_url: Optional[str] = None,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 3600,
    echo: bool = False
) -> None:
    """
    Initialize database engine and session factory

    Args:
        database_url: PostgreSQL connection URL (uses env vars if None)
        pool_size: Number of connections to keep in pool
        max_overflow: Maximum overflow connections
        pool_timeout: Timeout for getting connection from pool
        pool_recycle: Recycle connections after this many seconds
        echo: Enable SQL query logging
    """
    global _engine, _session_factory, _scoped_session

    if _engine is not None:
        logger.warning("Database already initialized")
        return

    # Get database URL
    if database_url is None:
        database_url = get_database_url()

    try:
        # Create engine with connection pooling
        # Determine connect args based on database type
        connect_args = {}
        if 'postgresql' in database_url:
            connect_args = {'connect_timeout': 10}

        _engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            echo=echo,
            connect_args=connect_args
        )

        # Add connection pool listeners
        @event.listens_for(_engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            """Log new connections"""
            logger.debug("New database connection established")

        @event.listens_for(_engine, "checkout")
        def receive_checkout(dbapi_conn, connection_record, connection_proxy):
            """Log connection checkouts"""
            logger.debug("Connection checked out from pool")

        # Create session factory
        _session_factory = sessionmaker(
            bind=_engine,
            autocommit=False,
            autoflush=False
        )

        # Create scoped session for thread-safety
        _scoped_session = scoped_session(_session_factory)

        logger.info("✅ Database initialized successfully")
        logger.info(f"   Pool size: {pool_size}")
        logger.info(f"   Max overflow: {max_overflow}")
        logger.info(f"   Pool timeout: {pool_timeout}s")
        logger.info(f"   Pool recycle: {pool_recycle}s")

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def get_engine():
    """
    Get database engine

    Returns:
        SQLAlchemy engine instance

    Raises:
        RuntimeError: If database not initialized
    """
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _engine


def get_session() -> Session:
    """
    Get a database session (scoped for thread safety)

    Returns:
        SQLAlchemy session

    Raises:
        RuntimeError: If database not initialized
    """
    if _scoped_session is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _scoped_session()


@contextmanager
def get_db_session():
    """
    Context manager for database sessions

    Automatically commits on success and rolls back on error.

    Usage:
        with get_db_session() as session:
            user = session.query(User).first()
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        session.close()


def close_database() -> None:
    """Close database connections and clean up resources"""
    global _engine, _session_factory, _scoped_session

    if _scoped_session:
        _scoped_session.remove()
        _scoped_session = None

    if _session_factory:
        _session_factory = None

    if _engine:
        _engine.dispose()
        _engine = None
        logger.info("Database connections closed")


def check_database_health() -> Dict[str, Any]:
    """
    Check database connection health

    Returns:
        Dictionary with health status and metrics
    """
    if _engine is None:
        return {
            'healthy': False,
            'error': 'Database not initialized'
        }

    try:
        # Try to execute a simple query
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        # Get pool status
        pool = _engine.pool
        pool_status = {
            'size': pool.size(),
            'checked_in': pool.checkedin(),
            'overflow': pool.overflow(),
            'checked_out': pool.size() - pool.checkedin()
        }

        return {
            'healthy': True,
            'pool': pool_status
        }

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            'healthy': False,
            'error': str(e)
        }


def test_connection() -> bool:
    """
    Test database connection

    Returns:
        True if connection successful, False otherwise
    """
    try:
        if _engine is None:
            logger.error("Database not initialized")
            return False

        with _engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            if result == 1:
                logger.info("✅ Database connection test successful")
                return True
            else:
                logger.error("Database connection test failed - unexpected result")
                return False

    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False


def get_pool_status() -> Dict[str, int]:
    """
    Get connection pool status

    Returns:
        Dictionary with pool metrics
    """
    if _engine is None or not hasattr(_engine, 'pool'):
        return {}

    pool = _engine.pool
    return {
        'size': pool.size(),
        'checked_in': pool.checkedin(),
        'overflow': pool.overflow(),
        'checked_out': pool.size() - pool.checkedin()
    }
