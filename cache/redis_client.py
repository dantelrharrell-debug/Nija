"""
NIJA Redis Cache Client

Manages Redis connections and provides caching utilities for:
- Market data caching
- Rate limiting
- User session management
- Permissions caching

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
import os
import json
import pickle
from typing import Optional, Any, Dict, List, Tuple
from datetime import timedelta
import redis
from redis.connection import ConnectionPool

logger = logging.getLogger(__name__)

# Global Redis client
_redis_client: Optional[redis.Redis] = None
_connection_pool: Optional[ConnectionPool] = None


def get_redis_url() -> str:
    """
    Get Redis URL from environment variables
    
    Returns:
        Redis connection URL
    """
    redis_url = os.getenv('REDIS_URL')
    
    if not redis_url:
        # Build from individual components
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = os.getenv('REDIS_PORT', '6379')
        redis_db = os.getenv('REDIS_DB', '0')
        redis_password = os.getenv('REDIS_PASSWORD', '')
        
        if redis_password:
            redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}"
        else:
            redis_url = f"redis://{redis_host}:{redis_port}/{redis_db}"
    
    return redis_url


def init_redis(
    redis_url: Optional[str] = None,
    max_connections: int = 50,
    decode_responses: bool = False,
    socket_timeout: int = 5,
    socket_connect_timeout: int = 5
) -> None:
    """
    Initialize Redis client with connection pooling
    
    Args:
        redis_url: Redis connection URL (uses env vars if None)
        max_connections: Maximum connections in pool
        decode_responses: Automatically decode responses to strings
        socket_timeout: Socket timeout in seconds
        socket_connect_timeout: Socket connect timeout in seconds
    """
    global _redis_client, _connection_pool
    
    if _redis_client is not None:
        logger.warning("Redis client already initialized")
        return
    
    # Get Redis URL
    if redis_url is None:
        redis_url = get_redis_url()
    
    try:
        # Create connection pool
        _connection_pool = ConnectionPool.from_url(
            redis_url,
            max_connections=max_connections,
            decode_responses=decode_responses,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout
        )
        
        # Create Redis client
        _redis_client = redis.Redis(connection_pool=_connection_pool)
        
        # Test connection
        _redis_client.ping()
        
        logger.info("✅ Redis client initialized successfully")
        logger.info(f"   Max connections: {max_connections}")
        logger.info(f"   Socket timeout: {socket_timeout}s")
        
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        raise


def get_redis_client() -> redis.Redis:
    """
    Get Redis client instance
    
    Returns:
        Redis client
        
    Raises:
        RuntimeError: If Redis not initialized
    """
    if _redis_client is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis_client


def close_redis() -> None:
    """Close Redis connections and clean up resources"""
    global _redis_client, _connection_pool
    
    if _connection_pool:
        _connection_pool.disconnect()
        _connection_pool = None
    
    if _redis_client:
        _redis_client.close()
        _redis_client = None
        logger.info("Redis connections closed")


def check_redis_health() -> Dict[str, Any]:
    """
    Check Redis connection health
    
    Returns:
        Dictionary with health status and metrics
    """
    if _redis_client is None:
        return {
            'healthy': False,
            'error': 'Redis not initialized'
        }
    
    try:
        # Test ping
        _redis_client.ping()
        
        # Get info
        info = _redis_client.info()
        
        return {
            'healthy': True,
            'version': info.get('redis_version', 'unknown'),
            'connected_clients': info.get('connected_clients', 0),
            'used_memory_human': info.get('used_memory_human', '0'),
            'total_keys': _redis_client.dbsize()
        }
    
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return {
            'healthy': False,
            'error': str(e)
        }


# Caching utilities

class CacheNamespace:
    """Cache key namespaces"""
    MARKET_DATA = "market:"
    USER_SESSION = "session:"
    USER_PERMISSIONS = "perm:"
    RATE_LIMIT = "rate:"
    POSITION_DATA = "position:"
    ACCOUNT_BALANCE = "balance:"


def cache_set(key: str, value: Any, ttl: Optional[int] = None, 
              namespace: str = "") -> bool:
    """
    Set a value in cache
    
    Args:
        key: Cache key
        value: Value to cache (will be JSON-encoded)
        ttl: Time to live in seconds (None = no expiration)
        namespace: Key namespace prefix
        
    Returns:
        True if successful, False otherwise
    """
    try:
        client = get_redis_client()
        full_key = f"{namespace}{key}"
        
        # Serialize value
        if isinstance(value, (dict, list)):
            serialized = json.dumps(value)
        elif isinstance(value, (int, float, str, bool)):
            serialized = str(value)
        else:
            # Use pickle for complex objects
            serialized = pickle.dumps(value)
        
        if ttl:
            client.setex(full_key, ttl, serialized)
        else:
            client.set(full_key, serialized)
        
        return True
    
    except Exception as e:
        logger.error(f"Cache set failed for key {key}: {e}")
        return False


def cache_get(key: str, namespace: str = "", default: Any = None) -> Any:
    """
    Get a value from cache
    
    Args:
        key: Cache key
        namespace: Key namespace prefix
        default: Default value if key not found
        
    Returns:
        Cached value or default
    """
    try:
        client = get_redis_client()
        full_key = f"{namespace}{key}"
        
        value = client.get(full_key)
        
        if value is None:
            return default
        
        # Try to deserialize
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # Try pickle
            try:
                return pickle.loads(value)
            except (pickle.UnpicklingError, TypeError, ValueError):
                # Return as string
                return value.decode('utf-8') if isinstance(value, bytes) else value
    
    except Exception as e:
        logger.error(f"Cache get failed for key {key}: {e}")
        return default


def cache_delete(key: str, namespace: str = "") -> bool:
    """
    Delete a key from cache
    
    Args:
        key: Cache key
        namespace: Key namespace prefix
        
    Returns:
        True if deleted, False otherwise
    """
    try:
        client = get_redis_client()
        full_key = f"{namespace}{key}"
        client.delete(full_key)
        return True
    
    except Exception as e:
        logger.error(f"Cache delete failed for key {key}: {e}")
        return False


def cache_exists(key: str, namespace: str = "") -> bool:
    """
    Check if a key exists in cache
    
    Args:
        key: Cache key
        namespace: Key namespace prefix
        
    Returns:
        True if exists, False otherwise
    """
    try:
        client = get_redis_client()
        full_key = f"{namespace}{key}"
        return bool(client.exists(full_key))
    
    except Exception as e:
        logger.error(f"Cache exists check failed for key {key}: {e}")
        return False


def cache_clear_namespace(namespace: str) -> int:
    """
    Clear all keys in a namespace
    
    Args:
        namespace: Namespace to clear
        
    Returns:
        Number of keys deleted
    """
    try:
        client = get_redis_client()
        pattern = f"{namespace}*"
        
        # Use scan_iter instead of keys() for better performance
        keys_to_delete = []
        for key in client.scan_iter(match=pattern, count=100):
            keys_to_delete.append(key)
            # Delete in batches of 1000 to avoid memory issues
            if len(keys_to_delete) >= 1000:
                client.delete(*keys_to_delete)
                count = len(keys_to_delete)
                keys_to_delete.clear()
        
        # Delete remaining keys
        if keys_to_delete:
            client.delete(*keys_to_delete)
            count = len(keys_to_delete)
        else:
            count = 0
        
        return count
    
    except Exception as e:
        logger.error(f"Cache clear namespace failed for {namespace}: {e}")
        return 0


# Rate limiting utilities

def rate_limit_check(identifier: str, max_requests: int, 
                    window_seconds: int) -> Tuple[bool, int]:
    """
    Check if rate limit is exceeded
    
    Args:
        identifier: Unique identifier (e.g., user_id, ip_address)
        max_requests: Maximum requests allowed in window
        window_seconds: Time window in seconds
        
    Returns:
        Tuple of (allowed: bool, remaining: int)
    """
    try:
        client = get_redis_client()
        key = f"{CacheNamespace.RATE_LIMIT}{identifier}"
        
        # Get current count
        count = client.get(key)
        
        if count is None:
            # First request in window
            client.setex(key, window_seconds, 1)
            return True, max_requests - 1
        
        count = int(count)
        
        if count >= max_requests:
            # Rate limit exceeded
            return False, 0
        
        # Increment and return
        new_count = client.incr(key)
        remaining = max(0, max_requests - new_count)
        
        return True, remaining
    
    except Exception as e:
        logger.error(f"Rate limit check failed for {identifier}: {e}")
        # On error, allow the request
        return True, max_requests


def rate_limit_reset(identifier: str) -> bool:
    """
    Reset rate limit for an identifier
    
    Args:
        identifier: Identifier to reset
        
    Returns:
        True if successful
    """
    return cache_delete(identifier, namespace=CacheNamespace.RATE_LIMIT)


# Market data caching

def cache_market_data(pair: str, timeframe: str, data: Dict[str, Any],
                     ttl: int = 60) -> bool:
    """
    Cache market data for a trading pair
    
    Args:
        pair: Trading pair (e.g., 'BTC-USD')
        timeframe: Timeframe (e.g., '1m', '5m', '1h')
        data: Market data dictionary
        ttl: Time to live in seconds (default: 60)
        
    Returns:
        True if successful
    """
    key = f"{pair}:{timeframe}"
    return cache_set(key, data, ttl=ttl, namespace=CacheNamespace.MARKET_DATA)


def get_cached_market_data(pair: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """
    Get cached market data
    
    Args:
        pair: Trading pair
        timeframe: Timeframe
        
    Returns:
        Market data dictionary or None
    """
    key = f"{pair}:{timeframe}"
    return cache_get(key, namespace=CacheNamespace.MARKET_DATA)


# User session caching

def cache_user_session(user_id: str, session_data: Dict[str, Any],
                      ttl: int = 3600) -> bool:
    """
    Cache user session data
    
    Args:
        user_id: User identifier
        session_data: Session data dictionary
        ttl: Time to live in seconds (default: 1 hour)
        
    Returns:
        True if successful
    """
    return cache_set(user_id, session_data, ttl=ttl, 
                    namespace=CacheNamespace.USER_SESSION)


def get_cached_user_session(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get cached user session
    
    Args:
        user_id: User identifier
        
    Returns:
        Session data or None
    """
    return cache_get(user_id, namespace=CacheNamespace.USER_SESSION)


def invalidate_user_session(user_id: str) -> bool:
    """
    Invalidate user session
    
    Args:
        user_id: User identifier
        
    Returns:
        True if successful
    """
    return cache_delete(user_id, namespace=CacheNamespace.USER_SESSION)


# Permissions caching

def cache_user_permissions(user_id: str, permissions: Dict[str, Any],
                          ttl: int = 300) -> bool:
    """
    Cache user permissions
    
    Args:
        user_id: User identifier
        permissions: Permissions dictionary
        ttl: Time to live in seconds (default: 5 minutes)
        
    Returns:
        True if successful
    """
    return cache_set(user_id, permissions, ttl=ttl,
                    namespace=CacheNamespace.USER_PERMISSIONS)


def get_cached_user_permissions(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get cached user permissions
    
    Args:
        user_id: User identifier
        
    Returns:
        Permissions dictionary or None
    """
    return cache_get(user_id, namespace=CacheNamespace.USER_PERMISSIONS)


def invalidate_user_permissions(user_id: str) -> bool:
    """
    Invalidate user permissions cache
    
    Args:
        user_id: User identifier
        
    Returns:
        True if successful
    """
    return cache_delete(user_id, namespace=CacheNamespace.USER_PERMISSIONS)
