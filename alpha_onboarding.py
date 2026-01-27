"""
NIJA Alpha User Onboarding System

Manages the onboarding flow for alpha users, including:
- Invitation code generation and validation
- User registration and verification
- Email verification workflow
- Broker credential setup
- Initial tier assignment
- Onboarding tutorial/wizard

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
import secrets
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from database.db_connection import get_db_session
from database.models import User, BrokerCredential
from auth import get_api_key_manager

logger = logging.getLogger(__name__)


class OnboardingStatus(Enum):
    """Onboarding workflow status"""
    INVITED = "invited"
    REGISTERED = "registered"
    EMAIL_VERIFIED = "email_verified"
    BROKER_CONNECTED = "broker_connected"
    TUTORIAL_COMPLETED = "tutorial_completed"
    ACTIVE = "active"


@dataclass
class InvitationCode:
    """Invitation code data structure"""
    code: str
    email: str
    created_at: datetime
    expires_at: datetime
    used: bool = False
    used_at: Optional[datetime] = None
    user_id: Optional[str] = None
    tier: str = "alpha"
    
    def is_valid(self) -> bool:
        """Check if invitation code is still valid"""
        if self.used:
            return False
        if datetime.now() > self.expires_at:
            return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'code': self.code,
            'email': self.email,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'used': self.used,
            'used_at': self.used_at.isoformat() if self.used_at else None,
            'user_id': self.user_id,
            'tier': self.tier,
            'is_valid': self.is_valid()
        }


@dataclass
class OnboardingState:
    """User onboarding state tracker"""
    user_id: str
    status: OnboardingStatus
    steps_completed: List[str] = field(default_factory=list)
    current_step: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'user_id': self.user_id,
            'status': self.status.value,
            'steps_completed': self.steps_completed,
            'current_step': self.current_step,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'progress_percent': self.get_progress_percent()
        }
    
    def get_progress_percent(self) -> int:
        """Calculate onboarding progress percentage"""
        total_steps = 5  # registration, email, broker, tutorial, activation
        return int((len(self.steps_completed) / total_steps) * 100)


class AlphaOnboardingSystem:
    """
    Alpha User Onboarding System
    
    Manages the complete onboarding workflow for alpha users,
    from invitation to full platform activation.
    """
    
    def __init__(self):
        """Initialize Alpha Onboarding System"""
        self._invitation_codes: Dict[str, InvitationCode] = {}
        self._onboarding_states: Dict[str, OnboardingState] = {}
        
        logger.info("✅ Alpha Onboarding System initialized")
    
    def generate_invitation_code(self, 
                                email: str, 
                                tier: str = "alpha",
                                validity_days: int = 7) -> InvitationCode:
        """
        Generate a unique invitation code for a user
        
        Args:
            email: User's email address
            tier: Subscription tier to assign (default: alpha)
            validity_days: Number of days until code expires (default: 7)
            
        Returns:
            InvitationCode object
        """
        # Generate secure random code
        random_bytes = secrets.token_bytes(16)
        code_hash = hashlib.sha256(random_bytes).hexdigest()[:12].upper()
        code = f"NIJA-{code_hash}"
        
        invitation = InvitationCode(
            code=code,
            email=email,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=validity_days),
            tier=tier
        )
        
        self._invitation_codes[code] = invitation
        
        logger.info(f"📧 Generated invitation code for {email}: {code}")
        
        return invitation
    
    def validate_invitation_code(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Validate an invitation code
        
        Args:
            code: Invitation code to validate
            
        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str])
        """
        if code not in self._invitation_codes:
            return False, "Invalid invitation code"
        
        invitation = self._invitation_codes[code]
        
        if invitation.used:
            return False, "Invitation code has already been used"
        
        if datetime.now() > invitation.expires_at:
            return False, "Invitation code has expired"
        
        return True, None
    
    def register_user(self, 
                     invitation_code: str,
                     email: str,
                     password_hash: str,
                     full_name: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Register a new user with an invitation code
        
        Args:
            invitation_code: Valid invitation code
            email: User's email address
            password_hash: Hashed password
            full_name: User's full name (optional)
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str], user_id: Optional[str])
        """
        # Validate invitation code
        is_valid, error = self.validate_invitation_code(invitation_code)
        if not is_valid:
            return False, error, None
        
        invitation = self._invitation_codes[invitation_code]
        
        # Verify email matches invitation
        if invitation.email != email:
            return False, "Email does not match invitation", None
        
        # Generate user ID
        user_id = f"user_{secrets.token_hex(8)}"
        
        try:
            # Create user in database
            with get_db_session() as session:
                # Check if user already exists
                existing_user = session.query(User).filter(User.email == email).first()
                if existing_user:
                    return False, "User already exists with this email", None
                
                # Create new user
                user = User(
                    user_id=user_id,
                    email=email,
                    subscription_tier=invitation.tier,
                    is_active=False  # Not active until onboarding complete
                )
                
                session.add(user)
                session.commit()
            
            # Mark invitation as used
            invitation.used = True
            invitation.used_at = datetime.now()
            invitation.user_id = user_id
            
            # Initialize onboarding state
            self._onboarding_states[user_id] = OnboardingState(
                user_id=user_id,
                status=OnboardingStatus.REGISTERED,
                steps_completed=['registration'],
                current_step='email_verification'
            )
            
            logger.info(f"✅ User registered: {user_id} ({email})")
            
            return True, None, user_id
            
        except Exception as e:
            logger.error(f"Error registering user: {e}")
            return False, f"Registration failed: {str(e)}", None
    
    def verify_email(self, user_id: str, verification_code: str) -> Tuple[bool, Optional[str]]:
        """
        Verify user's email address
        
        Args:
            user_id: User identifier
            verification_code: Email verification code
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        # TODO: Implement actual email verification logic
        # For now, this is a placeholder that always succeeds
        
        if user_id not in self._onboarding_states:
            return False, "User not found in onboarding"
        
        state = self._onboarding_states[user_id]
        
        # Update onboarding state
        state.status = OnboardingStatus.EMAIL_VERIFIED
        state.steps_completed.append('email_verification')
        state.current_step = 'broker_setup'
        
        logger.info(f"✅ Email verified for user: {user_id}")
        
        return True, None
    
    def setup_broker_credentials(self,
                                user_id: str,
                                broker: str,
                                api_key: str,
                                api_secret: str,
                                additional_params: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
        """
        Set up broker credentials for user
        
        Args:
            user_id: User identifier
            broker: Broker name (coinbase, kraken, binance, etc.)
            api_key: Broker API key
            api_secret: Broker API secret
            additional_params: Additional broker-specific parameters
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if user_id not in self._onboarding_states:
            return False, "User not found in onboarding"
        
        try:
            # Store encrypted credentials
            api_manager = get_api_key_manager()
            api_manager.store_user_api_key(
                user_id=user_id,
                broker=broker,
                api_key=api_key,
                api_secret=api_secret,
                additional_params=additional_params or {}
            )
            
            # Update onboarding state
            state = self._onboarding_states[user_id]
            state.status = OnboardingStatus.BROKER_CONNECTED
            state.steps_completed.append('broker_setup')
            state.current_step = 'tutorial'
            
            logger.info(f"✅ Broker credentials set up for user: {user_id} ({broker})")
            
            return True, None
            
        except Exception as e:
            logger.error(f"Error setting up broker credentials: {e}")
            return False, f"Failed to set up broker: {str(e)}"
    
    def complete_tutorial(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Mark tutorial as completed for user
        
        Args:
            user_id: User identifier
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if user_id not in self._onboarding_states:
            return False, "User not found in onboarding"
        
        state = self._onboarding_states[user_id]
        state.status = OnboardingStatus.TUTORIAL_COMPLETED
        state.steps_completed.append('tutorial')
        state.current_step = 'activation'
        
        logger.info(f"✅ Tutorial completed for user: {user_id}")
        
        return True, None
    
    def activate_user(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Activate user account and complete onboarding
        
        Args:
            user_id: User identifier
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if user_id not in self._onboarding_states:
            return False, "User not found in onboarding"
        
        state = self._onboarding_states[user_id]
        
        # Verify all required steps are completed
        required_steps = ['registration', 'email_verification', 'broker_setup', 'tutorial']
        missing_steps = [step for step in required_steps if step not in state.steps_completed]
        
        if missing_steps:
            return False, f"Missing required steps: {', '.join(missing_steps)}"
        
        try:
            # Activate user in database
            with get_db_session() as session:
                user = session.query(User).filter(User.user_id == user_id).first()
                if not user:
                    return False, "User not found"
                
                user.is_active = True
                session.commit()
            
            # Update onboarding state
            state.status = OnboardingStatus.ACTIVE
            state.steps_completed.append('activation')
            state.current_step = None
            state.completed_at = datetime.now()
            
            logger.info(f"🎉 User activated: {user_id}")
            
            return True, None
            
        except Exception as e:
            logger.error(f"Error activating user: {e}")
            return False, f"Activation failed: {str(e)}"
    
    def get_onboarding_status(self, user_id: str) -> Optional[OnboardingState]:
        """
        Get onboarding status for a user
        
        Args:
            user_id: User identifier
            
        Returns:
            OnboardingState object or None if not found
        """
        return self._onboarding_states.get(user_id)
    
    def get_all_invitations(self, 
                           include_used: bool = False,
                           include_expired: bool = False) -> List[InvitationCode]:
        """
        Get all invitation codes
        
        Args:
            include_used: Include used codes
            include_expired: Include expired codes
            
        Returns:
            List of InvitationCode objects
        """
        invitations = list(self._invitation_codes.values())
        
        if not include_used:
            invitations = [inv for inv in invitations if not inv.used]
        
        if not include_expired:
            invitations = [inv for inv in invitations if inv.is_valid()]
        
        return invitations
    
    def revoke_invitation(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Revoke an invitation code
        
        Args:
            code: Invitation code to revoke
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if code not in self._invitation_codes:
            return False, "Invitation code not found"
        
        invitation = self._invitation_codes[code]
        
        if invitation.used:
            return False, "Cannot revoke used invitation"
        
        # Set expiration to now
        invitation.expires_at = datetime.now()
        
        logger.info(f"🚫 Invitation code revoked: {code}")
        
        return True, None


# Global singleton instance
_onboarding_system: Optional[AlphaOnboardingSystem] = None


def get_onboarding_system() -> AlphaOnboardingSystem:
    """
    Get or create global onboarding system singleton
    
    Returns:
        AlphaOnboardingSystem instance
    """
    global _onboarding_system
    
    if _onboarding_system is None:
        _onboarding_system = AlphaOnboardingSystem()
        logger.info("Created new Alpha Onboarding System instance")
    
    return _onboarding_system


def reset_onboarding_system() -> None:
    """Reset global onboarding system (for testing)"""
    global _onboarding_system
    _onboarding_system = None
    logger.info("Alpha Onboarding System reset")
