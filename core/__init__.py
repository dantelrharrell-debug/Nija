"""
NIJA Core Brain - Layer 1 (PRIVATE)

This layer contains the proprietary strategy logic, risk engine, and decision systems.
🚫 NEVER EXPOSE THIS LAYER TO END USERS

Components:
- Strategy logic (trading decisions, indicators, signals)
- Risk engine (position sizing, risk calculations)
- Trade decision system (entry/exit logic)
- AI tuning and optimization

Access Control:
- Only internal modules can import from core
- No direct user access allowed
- All user interactions must go through execution or UI layers
"""

import sys
import logging
from typing import Optional

logger = logging.getLogger("nija.core")

# Access control flag
_CORE_ACCESS_VERIFIED = False


def verify_core_access(module_name: str) -> bool:
    """
    Verify that calling module has permission to access core layer.
    
    Args:
        module_name: Name of the module requesting access
    
    Returns:
        bool: True if access is allowed
    
    Raises:
        PermissionError: If unauthorized access is attempted
    """
    # Allow access from execution layer and internal components
    allowed_prefixes = [
        'execution.',
        'core.',
        'bot.',  # Legacy compatibility
        '__main__',
    ]
    
    for prefix in allowed_prefixes:
        if module_name.startswith(prefix) or module_name == prefix:
            return True
    
    # Deny all other access
    raise PermissionError(
        f"Unauthorized access to core layer from module: {module_name}. "
        f"Core strategy logic is private and cannot be accessed directly. "
        f"Use execution layer APIs instead."
    )


def _check_import_access():
    """Check if current import context is authorized."""
    import inspect
    frame = inspect.currentframe()
    if frame and frame.f_back:
        caller_module = frame.f_back.f_globals.get('__name__', '')
        try:
            verify_core_access(caller_module)
        except PermissionError as e:
            logger.error(f"Core access denied: {e}")
            raise


# Uncomment to enforce access control (disabled during migration)
# _check_import_access()

__all__ = [
    'verify_core_access',
]
