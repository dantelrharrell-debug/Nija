"""
NIJA Affiliate and Referral System
===================================

Viral growth loop mechanics with referral tracking and rewards.

Features:
- Referral code generation and tracking
- Multi-tier affiliate program
- Reward calculation and distribution
- Performance tracking
- Commission management
- Viral growth analytics

This creates viral growth loops by incentivizing users to refer others.

Author: NIJA Trading Systems
Version: 1.0 (Path 2)
Date: January 30, 2026
"""

import logging
import secrets
import string
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger("nija.affiliate")


class AffiliateStatus(Enum):
    """Affiliate program statuses"""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class RewardType(Enum):
    """Types of rewards"""
    COMMISSION = "commission"  # Percentage of referred user's revenue
    BONUS = "bonus"  # One-time bonus
    RECURRING = "recurring"  # Recurring monthly reward
    MILESTONE = "milestone"  # Milestone-based reward


@dataclass
class ReferralCode:
    """Referral code for a user"""
    code: str
    user_id: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    uses: int = 0
    max_uses: Optional[int] = None
    active: bool = True
    
    def is_valid(self) -> bool:
        """Check if code is valid"""
        if not self.active:
            return False
        
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        
        if self.max_uses and self.uses >= self.max_uses:
            return False
        
        return True
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'code': self.code,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'uses': self.uses,
            'max_uses': self.max_uses,
            'active': self.active,
            'is_valid': self.is_valid()
        }


@dataclass
class Referral:
    """A referral from one user to another"""
    referral_id: str
    referrer_user_id: str  # User who referred
    referred_user_id: str  # User who was referred
    referral_code: str
    created_at: datetime
    status: str  # pending, active, converted, churned
    conversion_date: Optional[datetime] = None
    lifetime_value: Decimal = Decimal('0')
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'referral_id': self.referral_id,
            'referrer_user_id': self.referrer_user_id,
            'referred_user_id': self.referred_user_id,
            'referral_code': self.referral_code,
            'created_at': self.created_at.isoformat(),
            'status': self.status,
            'conversion_date': self.conversion_date.isoformat() if self.conversion_date else None,
            'lifetime_value': float(self.lifetime_value)
        }


@dataclass
class AffiliateReward:
    """Reward for an affiliate"""
    reward_id: str
    user_id: str
    reward_type: RewardType
    amount_usd: Decimal
    source_referral_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    paid_at: Optional[datetime] = None
    status: str = "pending"  # pending, paid, cancelled
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'reward_id': self.reward_id,
            'user_id': self.user_id,
            'reward_type': self.reward_type.value,
            'amount_usd': float(self.amount_usd),
            'source_referral_id': self.source_referral_id,
            'created_at': self.created_at.isoformat(),
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'status': self.status
        }


@dataclass
class AffiliateStats:
    """Statistics for an affiliate"""
    user_id: str
    total_referrals: int = 0
    active_referrals: int = 0
    converted_referrals: int = 0
    total_earnings_usd: Decimal = Decimal('0')
    pending_earnings_usd: Decimal = Decimal('0')
    paid_earnings_usd: Decimal = Decimal('0')
    conversion_rate: float = 0.0
    avg_referral_value: Decimal = Decimal('0')
    
    def update_metrics(self):
        """Recalculate derived metrics"""
        if self.total_referrals > 0:
            self.conversion_rate = self.converted_referrals / self.total_referrals
            self.avg_referral_value = self.total_earnings_usd / self.total_referrals
        else:
            self.conversion_rate = 0.0
            self.avg_referral_value = Decimal('0')
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'user_id': self.user_id,
            'total_referrals': self.total_referrals,
            'active_referrals': self.active_referrals,
            'converted_referrals': self.converted_referrals,
            'total_earnings_usd': float(self.total_earnings_usd),
            'pending_earnings_usd': float(self.pending_earnings_usd),
            'paid_earnings_usd': float(self.paid_earnings_usd),
            'conversion_rate': self.conversion_rate,
            'avg_referral_value': float(self.avg_referral_value)
        }


class AffiliateReferralSystem:
    """
    Comprehensive affiliate and referral system
    
    Features:
    1. Referral Code Management
       - Generate unique codes
       - Track code usage
       - Code expiration
    
    2. Referral Tracking
       - Track who referred whom
       - Monitor referral lifecycle
       - Calculate conversion rates
    
    3. Reward Calculation
       - Commission-based rewards
       - Milestone bonuses
       - Recurring revenue share
    
    4. Multi-Tier Affiliate Program
       - Tier 1: Direct referrals (30% commission)
       - Tier 2: Indirect referrals (10% commission)
    
    5. Performance Analytics
       - Top affiliates
       - Conversion metrics
       - Revenue attribution
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize affiliate system
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Commission rates
        self.tier1_commission_rate = Decimal(str(self.config.get('tier1_commission_rate', 0.30)))  # 30%
        self.tier2_commission_rate = Decimal(str(self.config.get('tier2_commission_rate', 0.10)))  # 10%
        
        # Milestone bonuses
        self.milestone_bonuses = {
            5: Decimal('50.00'),  # $50 for 5 referrals
            10: Decimal('100.00'),  # $100 for 10 referrals
            25: Decimal('250.00'),  # $250 for 25 referrals
            50: Decimal('500.00'),  # $500 for 50 referrals
            100: Decimal('1000.00')  # $1000 for 100 referrals
        }
        
        # Storage (in production, use database)
        self.referral_codes: Dict[str, ReferralCode] = {}
        self.referrals: Dict[str, Referral] = {}
        self.rewards: Dict[str, AffiliateReward] = {}
        self.affiliate_stats: Dict[str, AffiliateStats] = {}
        
        logger.info("AffiliateReferralSystem initialized")
    
    def generate_referral_code(
        self,
        user_id: str,
        custom_code: Optional[str] = None,
        expires_days: Optional[int] = None,
        max_uses: Optional[int] = None
    ) -> ReferralCode:
        """
        Generate a referral code for a user
        
        Args:
            user_id: User identifier
            custom_code: Optional custom code
            expires_days: Optional expiration in days
            max_uses: Optional maximum number of uses
        
        Returns:
            ReferralCode
        """
        # Generate code
        if custom_code:
            code = custom_code.upper()
        else:
            code = self._generate_random_code(user_id)
        
        # Check for duplicates
        if code in self.referral_codes:
            logger.warning(f"Referral code {code} already exists, generating new one")
            code = self._generate_random_code(user_id)
        
        # Calculate expiration
        expires_at = None
        if expires_days:
            expires_at = datetime.now() + timedelta(days=expires_days)
        
        # Create referral code
        referral_code = ReferralCode(
            code=code,
            user_id=user_id,
            created_at=datetime.now(),
            expires_at=expires_at,
            max_uses=max_uses
        )
        
        self.referral_codes[code] = referral_code
        
        logger.info(f"Generated referral code {code} for user {user_id}")
        
        return referral_code
    
    def _generate_random_code(self, user_id: str, length: int = 8) -> str:
        """Generate random referral code"""
        # Use user_id prefix + random alphanumeric
        prefix = user_id[:3].upper()
        random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length - 3))
        return prefix + random_part
    
    def apply_referral_code(
        self,
        code: str,
        new_user_id: str
    ) -> Optional[Referral]:
        """
        Apply a referral code when a new user signs up
        
        Args:
            code: Referral code
            new_user_id: ID of new user being referred
        
        Returns:
            Referral object or None
        """
        # Get referral code
        referral_code = self.referral_codes.get(code.upper())
        
        if not referral_code:
            logger.warning(f"Referral code {code} not found")
            return None
        
        if not referral_code.is_valid():
            logger.warning(f"Referral code {code} is not valid")
            return None
        
        # Create referral
        referral_id = f"ref_{new_user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        referral = Referral(
            referral_id=referral_id,
            referrer_user_id=referral_code.user_id,
            referred_user_id=new_user_id,
            referral_code=code.upper(),
            created_at=datetime.now(),
            status='pending'
        )
        
        self.referrals[referral_id] = referral
        
        # Increment code usage
        referral_code.uses += 1
        
        # Update affiliate stats
        self._update_affiliate_stats(referral_code.user_id, new_referral=True)
        
        logger.info(
            f"Referral created: User {new_user_id} referred by {referral_code.user_id} "
            f"using code {code}"
        )
        
        return referral
    
    def mark_referral_converted(
        self,
        referral_id: str,
        subscription_tier: str,
        monthly_revenue: Decimal
    ):
        """
        Mark a referral as converted (user subscribed)
        
        Args:
            referral_id: Referral identifier
            subscription_tier: Tier user subscribed to
            monthly_revenue: Monthly subscription revenue
        """
        referral = self.referrals.get(referral_id)
        if not referral:
            logger.warning(f"Referral {referral_id} not found")
            return
        
        # Update referral status
        referral.status = 'converted'
        referral.conversion_date = datetime.now()
        
        # Calculate commission for referrer (Tier 1)
        tier1_commission = monthly_revenue * self.tier1_commission_rate
        
        # Create reward
        reward = self._create_reward(
            user_id=referral.referrer_user_id,
            reward_type=RewardType.COMMISSION,
            amount_usd=tier1_commission,
            source_referral_id=referral_id
        )
        
        # Update affiliate stats
        self._update_affiliate_stats(
            referral.referrer_user_id,
            converted=True,
            earnings=tier1_commission
        )
        
        # Check for milestone bonuses
        self._check_milestone_bonuses(referral.referrer_user_id)
        
        logger.info(
            f"Referral {referral_id} converted: ${tier1_commission:.2f} commission "
            f"for user {referral.referrer_user_id}"
        )
    
    def record_recurring_revenue(
        self,
        referred_user_id: str,
        revenue: Decimal
    ):
        """
        Record recurring revenue from a referred user
        
        Args:
            referred_user_id: Referred user's ID
            revenue: Revenue amount
        """
        # Find referral
        referral = None
        for ref in self.referrals.values():
            if ref.referred_user_id == referred_user_id:
                referral = ref
                break
        
        if not referral or referral.status != 'converted':
            return
        
        # Calculate commission
        commission = revenue * self.tier1_commission_rate
        
        # Create reward
        self._create_reward(
            user_id=referral.referrer_user_id,
            reward_type=RewardType.RECURRING,
            amount_usd=commission,
            source_referral_id=referral.referral_id
        )
        
        # Update lifetime value
        referral.lifetime_value += revenue
        
        # Update stats
        self._update_affiliate_stats(
            referral.referrer_user_id,
            earnings=commission
        )
    
    def _create_reward(
        self,
        user_id: str,
        reward_type: RewardType,
        amount_usd: Decimal,
        source_referral_id: Optional[str] = None
    ) -> AffiliateReward:
        """Create a reward"""
        reward_id = f"reward_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        reward = AffiliateReward(
            reward_id=reward_id,
            user_id=user_id,
            reward_type=reward_type,
            amount_usd=amount_usd,
            source_referral_id=source_referral_id
        )
        
        self.rewards[reward_id] = reward
        
        return reward
    
    def _update_affiliate_stats(
        self,
        user_id: str,
        new_referral: bool = False,
        converted: bool = False,
        earnings: Decimal = Decimal('0')
    ):
        """Update affiliate statistics"""
        if user_id not in self.affiliate_stats:
            self.affiliate_stats[user_id] = AffiliateStats(user_id=user_id)
        
        stats = self.affiliate_stats[user_id]
        
        if new_referral:
            stats.total_referrals += 1
            stats.active_referrals += 1
        
        if converted:
            stats.converted_referrals += 1
        
        if earnings > 0:
            stats.total_earnings_usd += earnings
            stats.pending_earnings_usd += earnings
        
        stats.update_metrics()
    
    def _check_milestone_bonuses(self, user_id: str):
        """Check and award milestone bonuses"""
        stats = self.affiliate_stats.get(user_id)
        if not stats:
            return
        
        # Check each milestone
        for milestone, bonus in self.milestone_bonuses.items():
            if stats.converted_referrals == milestone:
                # Award bonus
                self._create_reward(
                    user_id=user_id,
                    reward_type=RewardType.MILESTONE,
                    amount_usd=bonus
                )
                
                logger.info(
                    f"Milestone bonus awarded: ${bonus:.2f} for user {user_id} "
                    f"({milestone} referrals)"
                )
    
    def get_affiliate_stats(self, user_id: str) -> Optional[AffiliateStats]:
        """Get affiliate statistics for a user"""
        return self.affiliate_stats.get(user_id)
    
    def get_user_rewards(self, user_id: str, status: str = None) -> List[AffiliateReward]:
        """Get rewards for a user"""
        rewards = [r for r in self.rewards.values() if r.user_id == user_id]
        
        if status:
            rewards = [r for r in rewards if r.status == status]
        
        return rewards
    
    def get_top_affiliates(self, limit: int = 10) -> List[AffiliateStats]:
        """Get top affiliates by earnings"""
        stats_list = list(self.affiliate_stats.values())
        stats_list.sort(key=lambda x: x.total_earnings_usd, reverse=True)
        return stats_list[:limit]
    
    def get_system_stats(self) -> Dict:
        """Get overall system statistics"""
        total_referrals = sum(s.total_referrals for s in self.affiliate_stats.values())
        total_conversions = sum(s.converted_referrals for s in self.affiliate_stats.values())
        total_earnings = sum(s.total_earnings_usd for s in self.affiliate_stats.values())
        
        return {
            'total_affiliates': len(self.affiliate_stats),
            'total_referrals': total_referrals,
            'total_conversions': total_conversions,
            'total_earnings_usd': float(total_earnings),
            'overall_conversion_rate': total_conversions / total_referrals if total_referrals > 0 else 0.0,
            'active_codes': sum(1 for c in self.referral_codes.values() if c.is_valid())
        }


# Global instance
affiliate_referral_system = AffiliateReferralSystem()
