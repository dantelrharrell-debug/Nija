"""
NIJA Sector Cap State Layer
===========================

State management for sector-level position caps and exposure limits.
Integrates with portfolio state to enforce sector diversification.

This module provides:
- Real-time sector exposure tracking
- Soft and hard sector limits (15% soft, 20% hard)
- Sector correlation monitoring
- Integration with trading state machine

Sector limits prevent concentration risk and ensure diversification
across cryptocurrency sectors (DeFi, Layer-1, Meme Coins, etc.)

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from bot.crypto_sector_taxonomy import CryptoSector, get_sector, get_sector_name, get_highly_correlated_sectors

logger = logging.getLogger("nija.sector_cap_state")


class SectorLimitStatus(Enum):
    """Status of sector exposure relative to limits"""
    SAFE = "safe"  # Below soft limit
    WARNING = "warning"  # Between soft and hard limit
    HARD_LIMIT = "hard_limit"  # At or above hard limit
    CRITICAL = "critical"  # Far above hard limit


@dataclass
class SectorExposure:
    """Tracks exposure for a specific sector"""
    sector: CryptoSector
    total_value: float = 0.0  # Total USD value in this sector
    position_count: int = 0  # Number of positions
    symbols: Set[str] = field(default_factory=set)
    
    # Exposure as percentage of total portfolio
    exposure_pct: float = 0.0
    
    # Limit status
    status: SectorLimitStatus = SectorLimitStatus.SAFE
    soft_limit_pct: float = 15.0
    hard_limit_pct: float = 20.0
    
    # Warnings
    is_soft_limit_exceeded: bool = False
    is_hard_limit_exceeded: bool = False
    
    def update_exposure(self, total_portfolio_value: float):
        """Update exposure percentage and limit status"""
        if total_portfolio_value > 0:
            self.exposure_pct = (self.total_value / total_portfolio_value) * 100
        else:
            self.exposure_pct = 0.0
        
        # Update limit status
        self.is_soft_limit_exceeded = self.exposure_pct >= self.soft_limit_pct
        self.is_hard_limit_exceeded = self.exposure_pct >= self.hard_limit_pct
        
        # Determine status
        if self.exposure_pct >= self.hard_limit_pct * 1.5:
            self.status = SectorLimitStatus.CRITICAL
        elif self.exposure_pct >= self.hard_limit_pct:
            self.status = SectorLimitStatus.HARD_LIMIT
        elif self.exposure_pct >= self.soft_limit_pct:
            self.status = SectorLimitStatus.WARNING
        else:
            self.status = SectorLimitStatus.SAFE
    
    def can_add_position(self, position_value: float, total_portfolio_value: float) -> Tuple[bool, str]:
        """
        Check if a new position can be added without exceeding hard limit
        
        Args:
            position_value: Value of position to add
            total_portfolio_value: Current total portfolio value
            
        Returns:
            Tuple of (can_add, reason)
        """
        if total_portfolio_value <= 0:
            return True, "Portfolio value is zero"
        
        # Calculate what exposure would be after adding position
        new_total_value = self.total_value + position_value
        new_exposure_pct = (new_total_value / total_portfolio_value) * 100
        
        # Check hard limit
        if new_exposure_pct >= self.hard_limit_pct:
            return False, f"Would exceed hard limit ({self.hard_limit_pct}%) for {get_sector_name(self.sector)}"
        
        # Check soft limit (warning only)
        if new_exposure_pct >= self.soft_limit_pct:
            warning = f"Would exceed soft limit ({self.soft_limit_pct}%) for {get_sector_name(self.sector)}"
            logger.warning(f"⚠️  {warning}")
        
        return True, "OK"
    
    def get_available_capacity(self, total_portfolio_value: float) -> float:
        """
        Calculate how much more value can be added to this sector
        
        Args:
            total_portfolio_value: Current total portfolio value
            
        Returns:
            Available capacity in USD (up to hard limit)
        """
        if total_portfolio_value <= 0:
            return 0.0
        
        # Calculate max value allowed by hard limit
        max_value = total_portfolio_value * (self.hard_limit_pct / 100.0)
        
        # Subtract current exposure
        available = max_value - self.total_value
        
        return max(0.0, available)


@dataclass
class SectorCapState:
    """
    State management for sector-level position caps.
    
    This is the single source of truth for sector exposure limits.
    Integrates with portfolio state to enforce diversification.
    """
    
    # Sector exposure tracking
    sector_exposures: Dict[CryptoSector, SectorExposure] = field(default_factory=dict)
    
    # Global limits (can be overridden per sector)
    global_soft_limit_pct: float = 15.0
    global_hard_limit_pct: float = 20.0
    
    # Correlation tracking
    enable_correlation_limits: bool = True
    max_correlated_sectors_exposure_pct: float = 40.0  # Max combined exposure for correlated sectors
    
    # State metadata
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    total_portfolio_value: float = 0.0
    
    def initialize_sector(self, sector: CryptoSector):
        """Initialize a sector if not already tracked"""
        if sector not in self.sector_exposures:
            self.sector_exposures[sector] = SectorExposure(
                sector=sector,
                soft_limit_pct=self.global_soft_limit_pct,
                hard_limit_pct=self.global_hard_limit_pct
            )
    
    def update_position(
        self,
        symbol: str,
        position_value: float,
        add: bool = True
    ):
        """
        Update sector exposure when a position is added or removed
        
        Args:
            symbol: Trading symbol
            position_value: Position value in USD
            add: True to add position, False to remove
        """
        sector = get_sector(symbol)
        self.initialize_sector(sector)
        
        exposure = self.sector_exposures[sector]
        
        if add:
            exposure.total_value += position_value
            exposure.position_count += 1
            exposure.symbols.add(symbol)
        else:
            exposure.total_value = max(0, exposure.total_value - position_value)
            exposure.position_count = max(0, exposure.position_count - 1)
            if symbol in exposure.symbols:
                exposure.symbols.remove(symbol)
        
        # Update exposure percentages
        exposure.update_exposure(self.total_portfolio_value)
        
        self.last_updated = datetime.now().isoformat()
        
        logger.debug(
            f"Updated {get_sector_name(sector)} exposure: "
            f"${exposure.total_value:.2f} ({exposure.exposure_pct:.1f}%)"
        )
    
    def update_portfolio_value(self, total_value: float):
        """
        Update total portfolio value and recalculate all exposure percentages
        
        Args:
            total_value: Current total portfolio value
        """
        self.total_portfolio_value = total_value
        
        # Recalculate all sector exposure percentages
        for exposure in self.sector_exposures.values():
            exposure.update_exposure(total_value)
        
        self.last_updated = datetime.now().isoformat()
    
    def can_add_position(
        self,
        symbol: str,
        position_value: float
    ) -> Tuple[bool, str]:
        """
        Check if a position can be added without violating sector limits
        
        Args:
            symbol: Trading symbol
            position_value: Position value in USD
            
        Returns:
            Tuple of (can_add, reason)
        """
        sector = get_sector(symbol)
        self.initialize_sector(sector)
        
        # Check sector-specific hard limit
        can_add, reason = self.sector_exposures[sector].can_add_position(
            position_value, self.total_portfolio_value
        )
        
        if not can_add:
            return False, reason
        
        # Check correlated sectors if enabled
        if self.enable_correlation_limits:
            correlated_check = self._check_correlated_sectors(sector, position_value)
            if not correlated_check[0]:
                return correlated_check
        
        return True, "OK"
    
    def _check_correlated_sectors(
        self,
        sector: CryptoSector,
        additional_value: float
    ) -> Tuple[bool, str]:
        """
        Check if adding position would violate correlated sector limits
        
        Args:
            sector: Sector to add position in
            additional_value: Value to add
            
        Returns:
            Tuple of (can_add, reason)
        """
        correlated_map = get_highly_correlated_sectors()
        correlated_sectors = correlated_map.get(sector, set())
        
        if not correlated_sectors:
            return True, "No correlated sectors"
        
        # Calculate combined exposure of this sector + correlated sectors
        combined_value = additional_value
        
        # Add current exposure from this sector
        if sector in self.sector_exposures:
            combined_value += self.sector_exposures[sector].total_value
        
        # Add exposure from correlated sectors
        for corr_sector in correlated_sectors:
            if corr_sector in self.sector_exposures:
                combined_value += self.sector_exposures[corr_sector].total_value
        
        # Calculate combined exposure percentage
        if self.total_portfolio_value > 0:
            combined_pct = (combined_value / self.total_portfolio_value) * 100
        else:
            combined_pct = 0
        
        # Check limit
        if combined_pct > self.max_correlated_sectors_exposure_pct:
            sector_names = [get_sector_name(s) for s in [sector] + list(correlated_sectors)]
            return False, (
                f"Would exceed correlated sectors limit ({self.max_correlated_sectors_exposure_pct}%) "
                f"for {', '.join(sector_names)}"
            )
        
        return True, "OK"
    
    def get_sector_status(self, sector: CryptoSector) -> Optional[SectorExposure]:
        """Get exposure status for a specific sector"""
        return self.sector_exposures.get(sector)
    
    def get_all_exposures(self) -> Dict[CryptoSector, SectorExposure]:
        """Get all sector exposures"""
        return self.sector_exposures.copy()
    
    def get_sectors_at_limit(self) -> List[SectorExposure]:
        """Get all sectors at or above hard limit"""
        return [
            exp for exp in self.sector_exposures.values()
            if exp.is_hard_limit_exceeded
        ]
    
    def get_sectors_at_warning(self) -> List[SectorExposure]:
        """Get all sectors at or above soft limit but below hard limit"""
        return [
            exp for exp in self.sector_exposures.values()
            if exp.is_soft_limit_exceeded and not exp.is_hard_limit_exceeded
        ]
    
    def get_available_capacity(self, symbol: str) -> float:
        """
        Get available capacity for a symbol's sector
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Available capacity in USD
        """
        sector = get_sector(symbol)
        self.initialize_sector(sector)
        
        return self.sector_exposures[sector].get_available_capacity(
            self.total_portfolio_value
        )
    
    def get_summary(self) -> Dict:
        """Get comprehensive state summary"""
        sectors_at_limit = self.get_sectors_at_limit()
        sectors_at_warning = self.get_sectors_at_warning()
        
        # Calculate total exposure across all sectors
        total_exposure = sum(exp.total_value for exp in self.sector_exposures.values())
        
        return {
            'total_portfolio_value': self.total_portfolio_value,
            'total_sector_exposure': total_exposure,
            'sectors_tracked': len(self.sector_exposures),
            'sectors_at_hard_limit': len(sectors_at_limit),
            'sectors_at_soft_limit': len(sectors_at_warning),
            'global_soft_limit_pct': self.global_soft_limit_pct,
            'global_hard_limit_pct': self.global_hard_limit_pct,
            'last_updated': self.last_updated,
            'sector_exposures': {
                get_sector_name(sector): {
                    'value': exp.total_value,
                    'exposure_pct': exp.exposure_pct,
                    'position_count': exp.position_count,
                    'status': exp.status.value,
                    'soft_limit_exceeded': exp.is_soft_limit_exceeded,
                    'hard_limit_exceeded': exp.is_hard_limit_exceeded,
                    'available_capacity': exp.get_available_capacity(self.total_portfolio_value)
                }
                for sector, exp in self.sector_exposures.items()
                if exp.total_value > 0  # Only show sectors with exposure
            }
        }
    
    def get_health_status(self) -> Tuple[str, List[str]]:
        """
        Get overall health status of sector exposures
        
        Returns:
            Tuple of (status, warnings) where status is 'healthy', 'warning', or 'critical'
        """
        warnings = []
        
        sectors_at_limit = self.get_sectors_at_limit()
        sectors_at_warning = self.get_sectors_at_warning()
        
        # Check for critical violations
        critical_sectors = [
            exp for exp in self.sector_exposures.values()
            if exp.status == SectorLimitStatus.CRITICAL
        ]
        
        if critical_sectors:
            for exp in critical_sectors:
                warnings.append(
                    f"CRITICAL: {get_sector_name(exp.sector)} at {exp.exposure_pct:.1f}% "
                    f"(hard limit: {exp.hard_limit_pct}%)"
                )
            return "critical", warnings
        
        if sectors_at_limit:
            for exp in sectors_at_limit:
                warnings.append(
                    f"Hard limit exceeded: {get_sector_name(exp.sector)} at {exp.exposure_pct:.1f}%"
                )
            return "warning", warnings
        
        if sectors_at_warning:
            for exp in sectors_at_warning:
                warnings.append(
                    f"Soft limit exceeded: {get_sector_name(exp.sector)} at {exp.exposure_pct:.1f}%"
                )
            return "warning", warnings
        
        return "healthy", []


class SectorCapStateManager:
    """
    Global manager for sector cap state.
    
    Ensures sector limits are enforced across all trading operations.
    """
    
    def __init__(
        self,
        soft_limit_pct: float = 15.0,
        hard_limit_pct: float = 20.0,
        enable_correlation_limits: bool = True
    ):
        """
        Initialize sector cap state manager
        
        Args:
            soft_limit_pct: Soft limit percentage (default: 15%)
            hard_limit_pct: Hard limit percentage (default: 20%)
            enable_correlation_limits: Enable correlated sector limits
        """
        self.state = SectorCapState(
            global_soft_limit_pct=soft_limit_pct,
            global_hard_limit_pct=hard_limit_pct,
            enable_correlation_limits=enable_correlation_limits
        )
        
        logger.info("=" * 70)
        logger.info("🏷️  Sector Cap State Manager Initialized")
        logger.info("=" * 70)
        logger.info(f"Soft Limit: {soft_limit_pct}%")
        logger.info(f"Hard Limit: {hard_limit_pct}%")
        logger.info(f"Correlation Limits: {'Enabled' if enable_correlation_limits else 'Disabled'}")
        logger.info("=" * 70)
    
    def get_state(self) -> SectorCapState:
        """Get the current sector cap state"""
        return self.state
    
    def validate_new_position(
        self,
        symbol: str,
        position_value: float,
        total_portfolio_value: float
    ) -> Tuple[bool, str]:
        """
        Validate if a new position can be added
        
        Args:
            symbol: Trading symbol
            position_value: Position value in USD
            total_portfolio_value: Current total portfolio value
            
        Returns:
            Tuple of (is_valid, reason)
        """
        # Update portfolio value
        self.state.update_portfolio_value(total_portfolio_value)
        
        # Check if position can be added
        return self.state.can_add_position(symbol, position_value)
    
    def add_position(
        self,
        symbol: str,
        position_value: float,
        total_portfolio_value: float
    ):
        """
        Add a position and update sector exposure
        
        Args:
            symbol: Trading symbol
            position_value: Position value in USD
            total_portfolio_value: Current total portfolio value
        """
        self.state.update_portfolio_value(total_portfolio_value)
        self.state.update_position(symbol, position_value, add=True)
    
    def remove_position(
        self,
        symbol: str,
        position_value: float,
        total_portfolio_value: float
    ):
        """
        Remove a position and update sector exposure
        
        Args:
            symbol: Trading symbol
            position_value: Position value in USD
            total_portfolio_value: Current total portfolio value
        """
        self.state.update_portfolio_value(total_portfolio_value)
        self.state.update_position(symbol, position_value, add=False)


# Global singleton instance
_sector_cap_manager: Optional[SectorCapStateManager] = None


def get_sector_cap_manager() -> SectorCapStateManager:
    """Get or create the global sector cap state manager"""
    global _sector_cap_manager
    if _sector_cap_manager is None:
        _sector_cap_manager = SectorCapStateManager()
    return _sector_cap_manager


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Create manager
    manager = get_sector_cap_manager()
    state = manager.get_state()
    
    # Simulate adding positions
    portfolio_value = 10000.0
    
    # Add BTC position (15% of portfolio)
    state.update_portfolio_value(portfolio_value)
    state.update_position("BTC-USD", 1500.0, add=True)
    
    # Add ETH position (10% of portfolio)
    state.update_position("ETH-USD", 1000.0, add=True)
    
    # Add another BTC position - should trigger warning
    can_add, reason = state.can_add_position("BTC-USD", 700.0)
    print(f"\nCan add more BTC? {can_add} - {reason}")
    
    # Get summary
    summary = state.get_summary()
    print(f"\nSummary:")
    print(f"  Sectors tracked: {summary['sectors_tracked']}")
    print(f"  Sectors at warning: {summary['sectors_at_soft_limit']}")
    print(f"  Sectors at limit: {summary['sectors_at_hard_limit']}")
    
    # Get health status
    health, warnings = state.get_health_status()
    print(f"\nHealth: {health}")
    for warning in warnings:
        print(f"  - {warning}")
