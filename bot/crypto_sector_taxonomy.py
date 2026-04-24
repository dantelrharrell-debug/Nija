"""
Cryptocurrency Sector Taxonomy
================================

Defines clear sector classifications for cryptocurrency assets to enable
sector-level risk management and exposure limits.

This taxonomy is used for:
- Sector concentration limits (soft: 15%, hard: 20%)
- Portfolio diversification analysis
- Risk management across correlated asset groups

Author: NIJA Trading Systems
Version: 1.0
Date: February 12, 2026
"""

from enum import Enum
from typing import Dict, Optional, Set
import logging

logger = logging.getLogger("nija.crypto_sectors")


class CryptoSector(Enum):
    """
    Cryptocurrency sector classifications
    
    Sectors are designed to group assets that tend to move together
    or serve similar purposes in the crypto ecosystem.
    """
    # Core Infrastructure
    BITCOIN = "bitcoin"                    # BTC and BTC derivatives
    ETHEREUM = "ethereum"                  # ETH and ETH-based assets
    STABLECOINS = "stablecoins"           # USDT, USDC, DAI, etc.
    
    # Layer-1 Blockchains
    LAYER_1_ALT = "layer_1_alt"           # SOL, ADA, AVAX, DOT, etc.
    LAYER_1_EVM = "layer_1_evm"           # BSC, FTM, MATIC (when used as L1)
    
    # Layer-2 & Scaling
    LAYER_2 = "layer_2"                    # ARB, OP, MATIC, IMX, etc.
    
    # DeFi Ecosystem
    DEFI_LENDING = "defi_lending"         # AAVE, COMP, MKR, etc.
    DEFI_DEX = "defi_dex"                 # UNI, SUSHI, CAKE, etc.
    DEFI_DERIVATIVES = "defi_derivatives"  # GMX, SNX, PERP, etc.
    DEFI_STAKING = "defi_staking"         # LDO, RPL, etc.
    
    # Exchange & Infrastructure
    EXCHANGE_TOKENS = "exchange_tokens"    # BNB, CRO, FTT, etc.
    ORACLES = "oracles"                    # LINK, BAND, TRB, etc.
    
    # Application Layer
    GAMING_METAVERSE = "gaming_metaverse"  # AXS, SAND, MANA, etc.
    NFT_ECOSYSTEM = "nft_ecosystem"        # BLUR, LRC, etc.
    SOCIAL_MEDIA = "social_media"          # MASK, DESO, etc.
    
    # Speculative
    MEME_COINS = "meme_coins"             # DOGE, SHIB, PEPE, etc.
    AI_TOKENS = "ai_tokens"               # FET, AGIX, RNDR, etc.
    
    # Privacy & Security
    PRIVACY_COINS = "privacy_coins"        # XMR, ZEC, DASH, etc.
    
    # Other
    MISC = "misc"                          # Uncategorized or unknown


# Symbol to Sector Mapping
# This is a comprehensive mapping of common trading pairs to their sectors
SYMBOL_TO_SECTOR: Dict[str, CryptoSector] = {
    # Bitcoin
    "BTC-USD": CryptoSector.BITCOIN,
    "BTC-USDT": CryptoSector.BITCOIN,
    "BTCUSD": CryptoSector.BITCOIN,
    "WBTC-USD": CryptoSector.BITCOIN,
    
    # Ethereum
    "ETH-USD": CryptoSector.ETHEREUM,
    "ETH-USDT": CryptoSector.ETHEREUM,
    "ETHUSD": CryptoSector.ETHEREUM,
    "WETH-USD": CryptoSector.ETHEREUM,
    
    # Stablecoins
    "USDT-USD": CryptoSector.STABLECOINS,
    "USDC-USD": CryptoSector.STABLECOINS,
    "DAI-USD": CryptoSector.STABLECOINS,
    "BUSD-USD": CryptoSector.STABLECOINS,
    "TUSD-USD": CryptoSector.STABLECOINS,
    "USDD-USD": CryptoSector.STABLECOINS,
    
    # Layer-1 Alt (Non-EVM)
    "SOL-USD": CryptoSector.LAYER_1_ALT,
    "SOL-USDT": CryptoSector.LAYER_1_ALT,
    "ADA-USD": CryptoSector.LAYER_1_ALT,
    "ADA-USDT": CryptoSector.LAYER_1_ALT,
    "AVAX-USD": CryptoSector.LAYER_1_ALT,
    "AVAX-USDT": CryptoSector.LAYER_1_ALT,
    "DOT-USD": CryptoSector.LAYER_1_ALT,
    "DOT-USDT": CryptoSector.LAYER_1_ALT,
    "ATOM-USD": CryptoSector.LAYER_1_ALT,
    "ATOM-USDT": CryptoSector.LAYER_1_ALT,
    "NEAR-USD": CryptoSector.LAYER_1_ALT,
    "ALGO-USD": CryptoSector.LAYER_1_ALT,
    "XTZ-USD": CryptoSector.LAYER_1_ALT,
    "APT-USD": CryptoSector.LAYER_1_ALT,
    "SUI-USD": CryptoSector.LAYER_1_ALT,
    
    # Layer-1 EVM Compatible
    "FTM-USD": CryptoSector.LAYER_1_EVM,
    "FTM-USDT": CryptoSector.LAYER_1_EVM,
    "CELO-USD": CryptoSector.LAYER_1_EVM,
    
    # Layer-2 & Scaling
    "ARB-USD": CryptoSector.LAYER_2,
    "ARB-USDT": CryptoSector.LAYER_2,
    "OP-USD": CryptoSector.LAYER_2,
    "OP-USDT": CryptoSector.LAYER_2,
    "MATIC-USD": CryptoSector.LAYER_2,
    "MATIC-USDT": CryptoSector.LAYER_2,
    "IMX-USD": CryptoSector.LAYER_2,
    "LRC-USD": CryptoSector.LAYER_2,
    
    # DeFi - Lending
    "AAVE-USD": CryptoSector.DEFI_LENDING,
    "AAVE-USDT": CryptoSector.DEFI_LENDING,
    "COMP-USD": CryptoSector.DEFI_LENDING,
    "MKR-USD": CryptoSector.DEFI_LENDING,
    "CRV-USD": CryptoSector.DEFI_LENDING,
    
    # DeFi - DEX
    "UNI-USD": CryptoSector.DEFI_DEX,
    "UNI-USDT": CryptoSector.DEFI_DEX,
    "SUSHI-USD": CryptoSector.DEFI_DEX,
    "CAKE-USD": CryptoSector.DEFI_DEX,
    "1INCH-USD": CryptoSector.DEFI_DEX,
    
    # DeFi - Derivatives
    "GMX-USD": CryptoSector.DEFI_DERIVATIVES,
    "SNX-USD": CryptoSector.DEFI_DERIVATIVES,
    "PERP-USD": CryptoSector.DEFI_DERIVATIVES,
    "DYDX-USD": CryptoSector.DEFI_DERIVATIVES,
    
    # DeFi - Staking
    "LDO-USD": CryptoSector.DEFI_STAKING,
    "RPL-USD": CryptoSector.DEFI_STAKING,
    "RETH-USD": CryptoSector.DEFI_STAKING,
    "STETH-USD": CryptoSector.DEFI_STAKING,
    
    # Exchange Tokens
    "BNB-USD": CryptoSector.EXCHANGE_TOKENS,
    "BNB-USDT": CryptoSector.EXCHANGE_TOKENS,
    "CRO-USD": CryptoSector.EXCHANGE_TOKENS,
    "FTT-USD": CryptoSector.EXCHANGE_TOKENS,
    "HT-USD": CryptoSector.EXCHANGE_TOKENS,
    "OKB-USD": CryptoSector.EXCHANGE_TOKENS,
    
    # Oracles
    "LINK-USD": CryptoSector.ORACLES,
    "LINK-USDT": CryptoSector.ORACLES,
    "BAND-USD": CryptoSector.ORACLES,
    "TRB-USD": CryptoSector.ORACLES,
    "API3-USD": CryptoSector.ORACLES,
    
    # Gaming & Metaverse
    "AXS-USD": CryptoSector.GAMING_METAVERSE,
    "SAND-USD": CryptoSector.GAMING_METAVERSE,
    "MANA-USD": CryptoSector.GAMING_METAVERSE,
    "ENJ-USD": CryptoSector.GAMING_METAVERSE,
    "GALA-USD": CryptoSector.GAMING_METAVERSE,
    "IMX-USD": CryptoSector.GAMING_METAVERSE,
    
    # NFT Ecosystem
    "BLUR-USD": CryptoSector.NFT_ECOSYSTEM,
    "LOOKS-USD": CryptoSector.NFT_ECOSYSTEM,
    
    # Social Media
    "MASK-USD": CryptoSector.SOCIAL_MEDIA,
    
    # Meme Coins
    "DOGE-USD": CryptoSector.MEME_COINS,
    "DOGE-USDT": CryptoSector.MEME_COINS,
    "SHIB-USD": CryptoSector.MEME_COINS,
    "SHIB-USDT": CryptoSector.MEME_COINS,
    "PEPE-USD": CryptoSector.MEME_COINS,
    "FLOKI-USD": CryptoSector.MEME_COINS,
    
    # AI Tokens
    "FET-USD": CryptoSector.AI_TOKENS,
    "AGIX-USD": CryptoSector.AI_TOKENS,
    "RNDR-USD": CryptoSector.AI_TOKENS,
    "OCEAN-USD": CryptoSector.AI_TOKENS,
    
    # Privacy Coins
    "XMR-USD": CryptoSector.PRIVACY_COINS,
    "ZEC-USD": CryptoSector.PRIVACY_COINS,
    "DASH-USD": CryptoSector.PRIVACY_COINS,
}


def get_sector(symbol: str) -> CryptoSector:
    """
    Get the sector for a trading symbol
    
    Args:
        symbol: Trading pair symbol (e.g., "BTC-USD", "ETH-USDT")
        
    Returns:
        CryptoSector enum value
    """
    # Normalize symbol (uppercase, handle variations)
    normalized = symbol.upper().strip()
    
    # Direct lookup
    if normalized in SYMBOL_TO_SECTOR:
        return SYMBOL_TO_SECTOR[normalized]
    
    # Try without separator variations
    # Handle BTC-USD, BTCUSD, BTC/USD, BTC_USD
    for separator in ["-", "/", "_", ""]:
        test_symbol = normalized.replace(separator, "-")
        if test_symbol in SYMBOL_TO_SECTOR:
            return SYMBOL_TO_SECTOR[test_symbol]
    
    # Base currency heuristics (extract base from pair)
    base_currency = None
    for sep in ["-", "/", "_"]:
        if sep in normalized:
            base_currency = normalized.split(sep)[0]
            break
    
    if not base_currency:
        # No separator found, try common suffixes
        for suffix in ["USD", "USDT", "USDC", "BTC", "ETH"]:
            if normalized.endswith(suffix):
                base_currency = normalized[:-len(suffix)]
                break
    
    if base_currency:
        # Try base currency with common quote currencies
        for quote in ["USD", "USDT", "USDC", "BTC", "ETH"]:
            test = f"{base_currency}-{quote}"
            if test in SYMBOL_TO_SECTOR:
                return SYMBOL_TO_SECTOR[test]
    
    # Unknown sector
    logger.warning(f"Unknown sector for symbol: {symbol}, categorizing as MISC")
    return CryptoSector.MISC


def get_sector_name(sector: CryptoSector) -> str:
    """
    Get human-readable sector name
    
    Args:
        sector: CryptoSector enum
        
    Returns:
        Human-readable sector name
    """
    name_map = {
        CryptoSector.BITCOIN: "Bitcoin",
        CryptoSector.ETHEREUM: "Ethereum",
        CryptoSector.STABLECOINS: "Stablecoins",
        CryptoSector.LAYER_1_ALT: "Layer-1 (Alternative)",
        CryptoSector.LAYER_1_EVM: "Layer-1 (EVM)",
        CryptoSector.LAYER_2: "Layer-2 & Scaling",
        CryptoSector.DEFI_LENDING: "DeFi - Lending",
        CryptoSector.DEFI_DEX: "DeFi - DEX",
        CryptoSector.DEFI_DERIVATIVES: "DeFi - Derivatives",
        CryptoSector.DEFI_STAKING: "DeFi - Staking",
        CryptoSector.EXCHANGE_TOKENS: "Exchange Tokens",
        CryptoSector.ORACLES: "Oracles",
        CryptoSector.GAMING_METAVERSE: "Gaming & Metaverse",
        CryptoSector.NFT_ECOSYSTEM: "NFT Ecosystem",
        CryptoSector.SOCIAL_MEDIA: "Social Media",
        CryptoSector.MEME_COINS: "Meme Coins",
        CryptoSector.AI_TOKENS: "AI Tokens",
        CryptoSector.PRIVACY_COINS: "Privacy Coins",
        CryptoSector.MISC: "Miscellaneous",
    }
    return name_map.get(sector, sector.value)


def get_highly_correlated_sectors() -> Dict[CryptoSector, Set[CryptoSector]]:
    """
    Get sectors that tend to be highly correlated
    
    Returns:
        Dictionary mapping each sector to its correlated sectors
    """
    return {
        CryptoSector.DEFI_LENDING: {
            CryptoSector.DEFI_DEX,
            CryptoSector.DEFI_DERIVATIVES,
            CryptoSector.DEFI_STAKING,
        },
        CryptoSector.DEFI_DEX: {
            CryptoSector.DEFI_LENDING,
            CryptoSector.DEFI_DERIVATIVES,
        },
        CryptoSector.DEFI_DERIVATIVES: {
            CryptoSector.DEFI_LENDING,
            CryptoSector.DEFI_DEX,
        },
        CryptoSector.LAYER_1_ALT: {
            CryptoSector.LAYER_1_EVM,
        },
        CryptoSector.LAYER_1_EVM: {
            CryptoSector.LAYER_1_ALT,
            CryptoSector.LAYER_2,
        },
        CryptoSector.LAYER_2: {
            CryptoSector.LAYER_1_EVM,
            CryptoSector.ETHEREUM,
        },
        CryptoSector.GAMING_METAVERSE: {
            CryptoSector.NFT_ECOSYSTEM,
        },
        CryptoSector.NFT_ECOSYSTEM: {
            CryptoSector.GAMING_METAVERSE,
        },
    }


# Global sector exposure tracking (across all brokers)
# This ensures institutional-grade risk management where sector limits
# are enforced globally, not per-broker
GLOBAL_SECTOR_TRACKING = True

logger.info("=" * 70)
logger.info("🏷️  Cryptocurrency Sector Taxonomy Loaded")
logger.info("=" * 70)
logger.info(f"Total Sectors Defined: {len(CryptoSector)}")
logger.info(f"Mapped Symbols: {len(SYMBOL_TO_SECTOR)}")
logger.info(f"Sector Tracking: {'GLOBAL (all brokers)' if GLOBAL_SECTOR_TRACKING else 'PER-BROKER'}")
logger.info("=" * 70)
