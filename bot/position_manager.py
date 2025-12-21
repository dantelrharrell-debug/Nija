"""
NIJA Position Manager - Persistent Position Tracking

Saves and restores open positions to/from file so bot can restart without losing state.
Handles crash recovery and validates positions against broker on startup.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger("nija.positions")


class PositionManager:
    """
    Manages persistent storage of open trading positions.
    
    Features:
    - Save positions to JSON file on every update
    - Load positions on startup
    - Validate positions against broker API
    - Handle edge cases (positions closed externally)
    """
    
    def __init__(self, data_dir: str = "./data"):
        """
        Initialize position manager.
        
        Args:
            data_dir: Directory for position state file
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.positions_file = self.data_dir / "open_positions.json"
        logger.info(f"💾 Position manager initialized: {self.positions_file}")
    
    def save_positions(self, positions: Dict) -> bool:
        """
        Save current positions to file.
        
        Args:
            positions: Dictionary of open positions
        
        Returns:
            bool: True if save successful
        """
        try:
            # Add metadata
            state = {
                "timestamp": datetime.now().isoformat(),
                "positions": positions,
                "count": len(positions)
            }
            
            # Atomic write using temp file
            temp_file = self.positions_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)
            
            # Rename to final file (atomic on POSIX)
            temp_file.replace(self.positions_file)
            
            logger.debug(f"💾 Saved {len(positions)} positions to {self.positions_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save positions: {e}")
            return False
    
    def load_positions(self) -> Dict:
        """
        Load positions from file.
        
        Returns:
            dict: Restored positions or empty dict if file doesn't exist
        """
        if not self.positions_file.exists():
            logger.info("No saved positions found (first run)")
            return {}
        
        try:
            with open(self.positions_file, 'r') as f:
                state = json.load(f)
            
            positions = state.get('positions', {})
            timestamp = state.get('timestamp', 'unknown')
            count = len(positions)
            
            logger.info(f"💾 Loaded {count} positions from {timestamp}")
            
            # Log each restored position
            for symbol, pos in positions.items():
                logger.info(
                    f"  ↳ {symbol}: {pos.get('side')} @ ${pos.get('entry_price', 0):.4f} "
                    f"(Size: ${pos.get('position_size_usd', 0):.2f})"
                )
            
            return positions
            
        except json.JSONDecodeError as e:
            logger.error(f"Corrupted positions file: {e}")
            # Backup corrupted file
            backup = self.positions_file.with_suffix('.corrupted')
            self.positions_file.rename(backup)
            logger.warning(f"Moved corrupted file to {backup}")
            return {}
            
        except Exception as e:
            logger.error(f"Failed to load positions: {e}")
            return {}
    
    def validate_positions(self, positions: Dict, broker) -> Dict:
        """
        Validate loaded positions against broker API.
        
        Checks if positions still exist and updates with current prices.
        Removes positions that were closed externally.
        
        Args:
            positions: Loaded positions dict
            broker: Broker instance for API calls
        
        Returns:
            dict: Validated positions (may be subset of input)
        """
        if not positions:
            return {}
        
        logger.info(f"🔍 Validating {len(positions)} loaded positions against broker...")
        validated = {}
        
        for symbol, pos in positions.items():
            try:
                # Get current market data
                market_data = broker.get_market_data(symbol, timeframe='1m', limit=1)
                
                if not market_data or not market_data.get('candles'):
                    logger.warning(f"  ✗ {symbol}: No market data - removing position")
                    continue
                
                # Update with current price
                current_price = float(market_data['candles'][-1]['close'])
                pos['current_price'] = current_price
                
                # Calculate current P&L
                entry_price = float(pos.get('entry_price', 0))
                size_usd = float(pos.get('position_size_usd', 0))
                
                if pos.get('side') == 'BUY':
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                else:
                    pnl_pct = ((entry_price - current_price) / entry_price) * 100
                
                pos['unrealized_pnl_pct'] = pnl_pct
                validated[symbol] = pos
                
                logger.info(
                    f"  ✓ {symbol}: Valid @ ${current_price:.4f} "
                    f"(P&L: {pnl_pct:+.2f}%)"
                )
                
            except Exception as e:
                logger.error(f"  ✗ {symbol}: Validation failed - {e}")
                continue
        
        removed_count = len(positions) - len(validated)
        if removed_count > 0:
            logger.warning(f"⚠️  Removed {removed_count} invalid positions")
        
        logger.info(f"✅ Validated {len(validated)} positions")
        return validated
    
    def clear_positions(self) -> bool:
        """
        Clear all saved positions (e.g., manual reset).
        
        Returns:
            bool: True if clear successful
        """
        try:
            if self.positions_file.exists():
                # Backup before clearing
                backup = self.positions_file.with_suffix(
                    f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                )
                self.positions_file.rename(backup)
                logger.info(f"💾 Cleared positions (backup: {backup})")
            return True
        except Exception as e:
            logger.error(f"Failed to clear positions: {e}")
            return False
