"""
Environment Detection Utilities
================================

Provides utilities to detect the current environment (production, development, etc.)
for environment-specific behavior.
"""

import os


def is_production_environment() -> bool:
    """
    Detect if running in a production environment.
    
    Checks for common production environment indicators:
    - RAILWAY_ENVIRONMENT or RAILWAY_STATIC_URL (Railway deployment)
    - RENDER or RENDER_SERVICE_NAME (Render deployment)
    - HEROKU_APP_NAME (Heroku deployment)
    - COPILOT_AGENT_SOURCE_ENVIRONMENT=production (GitHub Copilot)
    - ENVIRONMENT=production
    - NIJA_ENV=production
    
    Returns:
        bool: True if running in production, False otherwise
    """
    # Check Railway
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_STATIC_URL"):
        return True
    
    # Check Render
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_NAME"):
        return True
    
    # Check Heroku
    if os.getenv("HEROKU_APP_NAME"):
        return True
    
    # Check GitHub Copilot production indicator
    if os.getenv("COPILOT_AGENT_SOURCE_ENVIRONMENT") == "production":
        return True
    
    # Check explicit environment variable
    env = os.getenv("ENVIRONMENT", "").lower()
    if env in ("production", "prod"):
        return True
    
    # Check NIJA-specific environment variable
    nija_env = os.getenv("NIJA_ENV", "").lower()
    if nija_env in ("production", "prod"):
        return True
    
    return False


def get_environment_name() -> str:
    """
    Get the current environment name.
    
    Returns:
        str: Environment name ("production", "development", "staging", etc.)
    """
    # Check explicit environment variable
    env = os.getenv("ENVIRONMENT", "").lower()
    if env:
        return env
    
    # Check NIJA-specific environment variable
    nija_env = os.getenv("NIJA_ENV", "").lower()
    if nija_env:
        return nija_env
    
    # Check GitHub Copilot
    copilot_env = os.getenv("COPILOT_AGENT_SOURCE_ENVIRONMENT", "").lower()
    if copilot_env:
        return copilot_env
    
    # Check platform-specific indicators
    if os.getenv("RAILWAY_ENVIRONMENT"):
        return "production"
    
    if os.getenv("RENDER"):
        return "production"
    
    if os.getenv("HEROKU_APP_NAME"):
        return "production"
    
    # Default to development
    return "development"


__all__ = [
    "is_production_environment",
    "get_environment_name",
]
