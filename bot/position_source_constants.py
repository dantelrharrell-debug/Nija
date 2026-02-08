"""
Position Source Constants and Utilities

Defines position source types and helper functions for categorizing positions
as NIJA-managed vs existing holdings.

Author: NIJA Trading Systems
Date: February 8, 2026
"""

from enum import Enum
from typing import Dict, Optional


class PositionSource(str, Enum):
    """
    Enum for position source types.
    
    Defines where a position originated from to distinguish between
    NIJA-managed positions and existing holdings.
    """
    NIJA_STRATEGY = "nija_strategy"  # Opened by NIJA trading algorithm
    BROKER_EXISTING = "broker_existing"  # Pre-existing position from before NIJA
    MANUAL = "manual"  # Manually entered by user
    UNKNOWN = "unknown"  # Source not yet determined


# Human-readable labels for each position source
POSITION_SOURCE_LABELS: Dict[str, str] = {
    PositionSource.NIJA_STRATEGY: "NIJA-Managed Position",
    PositionSource.BROKER_EXISTING: "Existing Holdings (not managed by NIJA)",
    PositionSource.MANUAL: "Existing Holdings (not managed by NIJA)",
    PositionSource.UNKNOWN: "Unknown Source",
}

# Detailed descriptions for each position source
POSITION_SOURCE_DESCRIPTIONS: Dict[str, str] = {
    PositionSource.NIJA_STRATEGY: "Opened by NIJA trading algorithm based on your configured strategy",
    PositionSource.BROKER_EXISTING: "Pre-existing position in your account before NIJA started",
    PositionSource.MANUAL: "Manually entered position (not created by NIJA)",
    PositionSource.UNKNOWN: "Position source has not been determined",
}


def is_nija_managed(position: Dict) -> bool:
    """
    Check if a position is managed by NIJA.
    
    Args:
        position: Position dictionary with 'position_source' key
        
    Returns:
        True if position is NIJA-managed, False otherwise
    """
    source = position.get('position_source', PositionSource.UNKNOWN)
    return source == PositionSource.NIJA_STRATEGY


def is_existing_holdings(position: Dict) -> bool:
    """
    Check if a position is an existing holding (not managed by NIJA).
    
    Args:
        position: Position dictionary with 'position_source' key
        
    Returns:
        True if position is existing holdings, False otherwise
    """
    source = position.get('position_source', PositionSource.UNKNOWN)
    return source in [
        PositionSource.BROKER_EXISTING,
        PositionSource.MANUAL,
        PositionSource.UNKNOWN
    ]


def get_source_label(source: str) -> str:
    """
    Get human-readable label for a position source.
    
    Args:
        source: Position source string
        
    Returns:
        Human-readable label
    """
    return POSITION_SOURCE_LABELS.get(source, "Unknown Source")


def get_source_description(source: str) -> str:
    """
    Get detailed description for a position source.
    
    Args:
        source: Position source string
        
    Returns:
        Detailed description
    """
    return POSITION_SOURCE_DESCRIPTIONS.get(source, "Position source has not been determined")


def categorize_positions(positions: list) -> Dict:
    """
    Categorize a list of positions by source.
    
    Args:
        positions: List of position dictionaries
        
    Returns:
        Dictionary with categorized positions:
        {
            'nija_managed': [...],
            'existing_holdings': [...],
            'counts': {
                'total': int,
                'nija_managed': int,
                'existing_holdings': int
            }
        }
    """
    nija_managed = [p for p in positions if is_nija_managed(p)]
    existing_holdings = [p for p in positions if is_existing_holdings(p)]
    
    return {
        'nija_managed': nija_managed,
        'existing_holdings': existing_holdings,
        'counts': {
            'total': len(positions),
            'nija_managed': len(nija_managed),
            'existing_holdings': len(existing_holdings)
        }
    }
