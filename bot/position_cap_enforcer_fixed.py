#!/usr/bin/env python3
"""
Position Cap Enforcer - Auto-reduce holdings to maximum allowed count

Ensures open position count never exceeds the cap.
Automatically sells lowest-momentum or most-exposed positions.
Runs before market entry to keep leverage under control.
"""

import os
import sys
import logging
from typing import Any, List, Dict, Tuple, Optional

# Setup logger
logger = logging.getLogger("nija.enforcer")

# Add bot dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

try:
    from broker_manager import CoinbaseBroker
except ImportError:
    logger.error("Failed to import broker_manager")
    CoinbaseBroker = None

try:
    from pipeline_order_submitter import submit_market_order_via_pipeline
except ImportError:
    submit_market_order_via_pipeline = None  # type: ignore


class PositionCapEnforcer:
    """
    Enforces maximum open position count by auto-liquidating excess positions.

    Safe, deterministic approach:
    - Reads current Coinbase holdings
    - Ranks by momentum (oversold/weak) or unrealized loss
    - Sells positions in order until count <= max_allowed
    """

    def __init__(self, max_positions: int = 8, broker: Optional[Any] = None):
        """
        Initialize position cap enforcer.

        Args:
            max_positions: Maximum allowed open positions (default: 8)
            broker: CoinbaseBroker instance (created if None)
        """
        self.max_positions = max_positions
        if broker is not None:
            self.broker = broker
        else:
            if CoinbaseBroker is None:
                raise RuntimeError("CoinbaseBroker unavailable; cannot initialize PositionCapEnforcer")
            self.broker = CoinbaseBroker()
        logger.info(f"PositionCapEnforcer initialized: max={max_positions} positions")

    def get_current_positions(self) -> List[Dict]:
        """
        Fetch current crypto holdings from Coinbase.

        Returns:
            List of position dicts: {'symbol', 'currency', 'balance', 'price', 'usd_value'}
        """
        try:
            if not self.broker.connect():
                logger.error("Failed to connect to broker")
                return []

            accounts = self.broker.client.get_accounts()
            positions = []

            # Handle both dict and object responses from Coinbase SDK
            accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])
            accounts_list = accounts_list or []

            for account in accounts_list:
                # Handle both dict and object account formats
                if isinstance(account, dict):
                    currency = account.get('currency')
                    balance_obj = account.get('available_balance', {})
                    balance = float(balance_obj.get('value', 0)) if balance_obj else 0
                else:
                    # Account object from Coinbase SDK
                    currency = getattr(account, 'currency', None)
                    balance_obj = getattr(account, 'available_balance', {})
                    balance = float(balance_obj.get('value', 0)) if isinstance(balance_obj, dict) else float(getattr(balance_obj, 'value', 0)) if balance_obj else 0

                if not currency or balance <= 0 or currency in ['USD', 'USDC']:
                    continue

                symbol = f"{currency}-USD"
                try:
                    product = self.broker.client.get_product(symbol)
                    price = float(product.price)
                    usd_value = balance * price

                    positions.append({
                        'symbol': symbol,
                        'currency': currency,
                        'balance': balance,
                        'price': price,
                        'usd_value': usd_value
                    })
                except Exception as e:
                    logger.warning(f"Could not fetch price for {symbol}: {e}")

            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def rank_positions_for_liquidation(self, positions: List[Dict]) -> List[Dict]:
        """
        Rank positions by priority for liquidation (lowest momentum first).

        Strategy: Sell weakest/losing positions first to preserve winners.

        Args:
            positions: List of position dicts

        Returns:
            Ranked list (highest-priority-to-sell first)
        """
        # For now: rank by smallest USD value (easier to exit, less slippage)
        # In future: rank by RSI (oversold), momentum, or drawdown
        ranked = sorted(positions, key=lambda p: p['usd_value'])

        logger.info(f"Ranked {len(ranked)} positions for liquidation (smallest first):")
        for i, pos in enumerate(ranked, 1):
            logger.info(f"  {i}. {pos['symbol']}: ${pos['usd_value']:.2f}")

        return ranked

    def sell_position(self, position: Dict) -> bool:
        """
        Market-sell a single position.

        Args:
            position: Position dict with 'symbol', 'balance', etc.

        Returns:
            True if successful, False otherwise
        """
        symbol = position['symbol']
        balance = position['balance']
        currency = position['currency']

        if submit_market_order_via_pipeline is None:
            logger.error("ExecutionPipeline submit helper unavailable; direct broker bypass blocked")
            return False

        try:
            logger.info(f"🔴 ENFORCER: Selling {currency}... (${position['usd_value']:.2f})")
            order = submit_market_order_via_pipeline(
                broker=self.broker,
                symbol=symbol,
                side='sell',
                quantity=balance,
                size_type='base',
                strategy='PositionCapEnforcerFixed',
            )

            if order and order.get('status') in ('filled', 'completed', 'success'):
                logger.info(f"✅ SOLD {currency}! Order placed.")
                return True

            logger.error(f"❌ Sell rejected for {symbol}: {order}")
            return False

        except Exception as e:
            logger.error(f"❌ Error selling {symbol}: {e}")
            return False

    def enforce_cap(self) -> Tuple[bool, Dict]:
        """
        Enforce position cap by auto-selling excess positions.

        Returns:
            (success: bool, result_dict with counts and actions)
        """
        logger.info(f"🔍 ENFORCE: Checking position cap (max={self.max_positions})...")

        positions = self.get_current_positions()
        current_count = len(positions)

        logger.info(f"   Current positions: {current_count}")

        if current_count <= self.max_positions:
            logger.info(f"✅ Under cap (no action needed)")
            return True, {
                'current_count': current_count,
                'max_allowed': self.max_positions,
                'excess': 0,
                'sold': 0,
                'status': 'compliant'
            }

        # Over cap: liquidate excess
        excess = current_count - self.max_positions
        logger.warning(f"🚨 OVER CAP by {excess} positions! Auto-liquidating...")

        ranked = self.rank_positions_for_liquidation(positions)
        sold_count = 0

        for i, pos in enumerate(ranked[:excess]):
            logger.info(f"\nSelling position {i+1}/{excess}...")
            if self.sell_position(pos):
                sold_count += 1
                import time
                time.sleep(1)  # Rate-limit API calls

        logger.info(f"\n" + "="*70)
        logger.info(f"ENFORCER SUMMARY: Sold {sold_count}/{excess} excess positions")
        logger.info(f"="*70)

        return sold_count == excess, {
            'current_count': current_count,
            'max_allowed': self.max_positions,
            'excess': excess,
            'sold': sold_count,
            'status': 'enforced' if sold_count == excess else 'partial'
        }


def main():
    """Run position cap enforcer as standalone script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
    )

    enforcer = PositionCapEnforcer(max_positions=8)
    success, result = enforcer.enforce_cap()

    if success:
        logger.info(f"✅ Position cap enforced successfully")
    else:
        logger.warning(f"⚠️ Partial enforcement: {result['sold']}/{result['excess']} sold")

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
