"""
NIJA Platform - FastAPI Backend

This is the production-grade API server using FastAPI instead of Flask.
It provides high-performance, async API endpoints for controlling NIJA.

Architecture:
  [ Mobile App / Web Dashboard ]
            ↓
  [ FastAPI Backend ] ← YOU ARE HERE
            ↓
  [ NIJA Trading Engine (Headless Microservice) ]
            ↓
  [ Exchanges ]
"""

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
import jwt
import hashlib
import secrets
import json
import os
import logging
import time
import stripe

from auth import get_api_key_manager, get_user_manager
from auth.user_database import get_user_database
from auth.two_factor import get_two_factor_auth
from auth.email_service import get_email_service
from auth.audit_log import get_auth_audit_log
from vault import get_vault
from execution import get_permission_validator, UserPermissions
from user_control import get_user_control_backend

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NIJA Trading Platform API",
    description="Autonomous cryptocurrency trading with AI-powered strategies",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_tags=[
        {"name": "health", "description": "Health check and monitoring endpoints"},
        {"name": "auth", "description": "Authentication and user management"},
        {"name": "brokers", "description": "Exchange API credential management"},
        {"name": "trading", "description": "Trading bot control and monitoring"},
        {"name": "analytics", "description": "Performance analytics and reporting"},
    ]
)

# CORS configuration - Security: Require explicit origins
allowed_origins_str = os.getenv('ALLOWED_ORIGINS', '')
if not allowed_origins_str:
    # Development fallback - still restrictive
    allowed_origins = ['http://localhost:3000', 'http://localhost:5173']
    print("⚠️ WARNING: ALLOWED_ORIGINS not set, using localhost defaults")
else:
    allowed_origins = allowed_origins_str.split(',')

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # Explicit methods only
    allow_headers=["Content-Type", "Authorization"],  # Whitelist headers
)

# Trusted host middleware (security)
if os.getenv('TRUSTED_HOSTS'):
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=os.getenv('TRUSTED_HOSTS').split(',')
    )

# Configuration - Security: Require JWT secret
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
if not JWT_SECRET_KEY:
    raise ValueError(
        "JWT_SECRET_KEY environment variable is required. "
        "Generate a secure secret: openssl rand -hex 32"
    )
if len(JWT_SECRET_KEY) < 32:
    raise ValueError(
        "JWT_SECRET_KEY must be at least 32 characters for security."
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))

# Get manager instances
api_key_manager = get_api_key_manager()
user_manager = get_user_manager()
user_db = get_user_database()  # Database-backed user management
vault = get_vault()  # Secure credential vault
permission_validator = get_permission_validator()
user_control = get_user_control_backend()
two_fa = get_two_factor_auth()       # TOTP two-factor authentication
email_svc = get_email_service()      # Transactional email service
audit_log = get_auth_audit_log()     # Auth event audit log

# Security
security = HTTPBearer()

# Rate limiting storage (in-memory, use Redis in production)
rate_limit_storage = defaultdict(list)
RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', '100'))
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '60'))  # seconds


# ========================================
# Pydantic Models (Request/Response)
# ========================================

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    subscription_tier: str = Field(default="basic", pattern="^(basic|pro|enterprise)$")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    subscription_tier: str


class UserProfile(BaseModel):
    user_id: str
    email: str
    subscription_tier: str
    created_at: str
    enabled: bool
    brokers: List[str]
    permissions: Optional[Dict] = None


class BrokerCredentials(BaseModel):
    api_key: str
    api_secret: str
    additional_params: Optional[Dict] = None


class TradingControl(BaseModel):
    action: str = Field(..., pattern="^(start|stop|pause)$")


class TradingStatus(BaseModel):
    user_id: str
    trading_enabled: bool
    engine_status: str
    last_activity: Optional[str] = None
    stats: Dict


class Position(BaseModel):
    pair: str
    side: str
    size: float
    entry_price: float
    current_price: float
    pnl: float
    pnl_percent: float


class Stats(BaseModel):
    user_id: str
    total_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0
    active_positions: int = 0


# ========================================
# Helper Functions
# ========================================

# Password hashing is now handled by user_db (Argon2)


def create_access_token(user_id: str) -> str:
    """Create JWT access token."""
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict]:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Invalid JWT token")
        return None


async def check_rate_limit(request: Request, user_id: str = None):
    """
    Rate limiting middleware - prevents API abuse.

    Args:
        request: FastAPI request object
        user_id: Optional user ID for per-user limits

    Raises:
        HTTPException: If rate limit exceeded
    """
    # Use IP address or user_id as key
    key = user_id if user_id else request.client.host if request.client else "unknown"
    current_time = time.time()

    # Get request timestamps for this key
    timestamps = rate_limit_storage[key]

    # Remove timestamps outside the window
    timestamps = [t for t in timestamps if current_time - t < RATE_LIMIT_WINDOW]

    # Check if limit exceeded
    if len(timestamps) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds."
        )

    # Add current request
    timestamps.append(current_time)
    rate_limit_storage[key] = timestamps


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Dependency to get current authenticated user from JWT token.

    Returns:
        str: User ID

    Raises:
        HTTPException: If token is invalid or expired
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload['user_id']

    # Check rate limit for authenticated user
    await check_rate_limit(request, user_id)

    return user_id


# ========================================
# Health & Info Endpoints
# ========================================

@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "NIJA FastAPI Backend",
        "version": "2.0.0"
    }


@app.get("/api/info", tags=["health"])
async def get_info():
    """Get API information and available endpoints."""
    return {
        "name": "NIJA Trading Platform API",
        "version": "2.0.0",
        "stack": {
            "backend": "FastAPI",
            "database": "PostgreSQL (planned)",
            "cache": "Redis (planned)",
            "container": "Docker"
        },
        "architecture": {
            "layer_1": "Core Brain (PRIVATE - Strategy & AI)",
            "layer_2": "Execution Engine (Headless Microservice)",
            "layer_3": "FastAPI Backend (YOU ARE HERE)"
        },
        "docs": {
            "swagger": "/api/docs",
            "redoc": "/api/redoc"
        }
    }


# ========================================
# Authentication Endpoints
# ========================================

@app.post("/api/auth/register", response_model=TokenResponse, tags=["auth"])
async def register(user_data: UserRegister, request: Request):
    """
    Register a new user account.

    Returns JWT token for immediate login.
    """
    email = user_data.email.lower().strip()

    # Check if user exists
    existing_user = user_db.get_user_by_email(email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists"
        )

    # Create user ID
    user_id = f"user_{secrets.token_hex(8)}"

    # Create user in database with password hashing
    success = user_db.create_user(
        user_id=user_id,
        email=email,
        password=user_data.password,  # Will be hashed by user_db
        subscription_tier=user_data.subscription_tier
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )

    # Register permissions based on tier
    max_position_size = {
        'basic': 100.0,
        'pro': 1000.0,
        'enterprise': 10000.0
    }.get(user_data.subscription_tier, 100.0)

    permissions = UserPermissions(
        user_id=user_id,
        max_position_size_usd=max_position_size,
        max_daily_loss_usd=max_position_size * 0.5,
        max_positions=3 if user_data.subscription_tier == 'basic' else 10
    )
    permission_validator.register_user(permissions)

    # Generate token
    token = create_access_token(user_id)

    logger.info(f"✅ New user registered: {email} (ID: {user_id}, Tier: {user_data.subscription_tier})")

    # Send verification email (non-blocking – failure logged, not raised)
    ip_address = request.client.host if request.client else None
    try:
        email_svc.send_verification_email(user_id=user_id, email=email)
    except Exception as exc:
        logger.error(f"Failed to send verification email to {email}: {exc}")

    audit_log.register(user_id=user_id, email=email, ip=ip_address or "")

    return TokenResponse(
        access_token=token,
        user_id=user_id,
        email=email,
        subscription_tier=user_data.subscription_tier
    )


@app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(credentials: UserLogin, request: Request):
    """
    Login user and return JWT token.
    """
    email = credentials.email.lower().strip()

    # Get user from database
    user_profile = user_db.get_user_by_email(email)

    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # Get IP address for audit logging
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    # Verify password (uses Argon2)
    if not user_db.verify_password(user_profile['user_id'], credentials.password, ip_address):
        audit_log.login_failure(
            user_id=user_profile['user_id'], ip=ip_address or "",
            user_agent=user_agent, reason="invalid_password"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    if not user_profile.get('enabled', True):
        audit_log.login_failure(
            user_id=user_profile['user_id'], ip=ip_address or "",
            user_agent=user_agent, reason="account_disabled"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled"
        )

    user_id = user_profile['user_id']

    # Generate token
    token = create_access_token(user_id)

    audit_log.login_success(user_id=user_id, ip=ip_address or "", user_agent=user_agent)
    logger.info(f"✅ User logged in: {email} (ID: {user_id})")

    return TokenResponse(
        access_token=token,
        user_id=user_id,
        email=email,
        subscription_tier=user_profile.get('subscription_tier', 'basic')
    )


# ========================================
# User Management Endpoints
# ========================================

@app.get("/api/user/profile", response_model=UserProfile, tags=["auth"])
async def get_profile(user_id: str = Depends(get_current_user)):
    """Get current user's profile."""
    user_profile = user_manager.get_user(user_id)

    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    permissions = permission_validator.get_user_permissions(user_id)

    return UserProfile(
        user_id=user_id,
        email=user_profile['email'],
        subscription_tier=user_profile['subscription_tier'],
        created_at=user_profile['created_at'],
        enabled=user_profile['enabled'],
        brokers=api_key_manager.list_user_brokers(user_id),
        permissions=permissions.to_dict() if permissions else None
    )


# ========================================
# Broker Management Endpoints
# ========================================

@app.get("/api/user/brokers", tags=["brokers"])
async def list_brokers(user_id: str = Depends(get_current_user)):
    """List all configured brokers for user."""
    brokers = vault.list_user_brokers(user_id)
    return {"user_id": user_id, "brokers": brokers, "count": len(brokers)}


@app.post("/api/user/brokers/{broker_name}", tags=["brokers"])
async def add_broker(
    broker_name: str,
    credentials: BrokerCredentials,
    request: Request,
    user_id: str = Depends(get_current_user)
):
    """Add broker API credentials to secure vault."""
    supported_brokers = ['coinbase', 'kraken', 'binance', 'okx', 'alpaca']

    if broker_name.lower() not in supported_brokers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported broker. Supported: {', '.join(supported_brokers)}"
        )

    # Get IP address for audit logging
    ip_address = request.client.host if request.client else None

    # Store encrypted credentials in secure vault
    success = vault.store_credentials(
        user_id=user_id,
        broker=broker_name.lower(),
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
        additional_params=credentials.additional_params,
        ip_address=ip_address
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store credentials"
        )

    logger.info(f"✅ User {user_id} added {broker_name} credentials")

    return {"message": f"{broker_name} credentials added successfully", "broker": broker_name}


@app.delete("/api/user/brokers/{broker_name}", tags=["brokers"])
async def remove_broker(
    broker_name: str,
    request: Request,
    user_id: str = Depends(get_current_user)
):
    """Remove broker API credentials from secure vault."""
    ip_address = request.client.host if request.client else None

    # Remove from vault
    success = vault.delete_credentials(user_id, broker_name.lower(), ip_address)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {broker_name} credentials found"
        )

    logger.info(f"✅ User {user_id} removed {broker_name} credentials")

    return {"message": f"{broker_name} credentials removed successfully"}


# ========================================
# NIJA Bot Control Endpoints (Headless Microservice Interface)
# ========================================

@app.post("/api/start_bot", tags=["trading"])
async def start_bot(user_id: str = Depends(get_current_user)):
    """
    Start NIJA trading bot for user.

    This endpoint starts a headless NIJA instance for this user.
    The bot runs autonomously until stopped.
    """
    result = user_control.start_trading(user_id)

    if not result.get('success'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get('error', 'Failed to start bot')
        )

    logger.info(f"▶️ Started NIJA bot for user {user_id}")

    return {
        "message": "NIJA bot started successfully",
        "user_id": user_id,
        "status": result.get('status')
    }


@app.post("/api/stop_bot", tags=["trading"])
async def stop_bot(user_id: str = Depends(get_current_user)):
    """
    Stop NIJA trading bot for user.

    This gracefully stops the bot, closing positions and canceling orders.
    """
    result = user_control.stop_trading(user_id)

    if not result.get('success'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get('error', 'Failed to stop bot')
        )

    logger.info(f"⏹️ Stopped NIJA bot for user {user_id}")

    return {
        "message": "NIJA bot stopped successfully",
        "user_id": user_id,
        "status": result.get('status')
    }


@app.get("/api/status", response_model=TradingStatus, tags=["trading"])
async def get_status(user_id: str = Depends(get_current_user)):
    """
    Get current NIJA bot status for user.

    Returns real-time status without exposing strategy internals.
    """
    status = user_control.get_user_status(user_id)

    return TradingStatus(
        user_id=user_id,
        trading_enabled=status.get('status') == 'running',
        engine_status=status.get('status', 'unknown'),
        last_activity=status.get('last_activity'),
        stats=status.get('stats', {})
    )


@app.get("/api/positions", response_model=List[Position], tags=["trading"])
async def get_positions(user_id: str = Depends(get_current_user)):
    """
    Get active trading positions.

    Returns current positions without exposing entry/exit logic.
    """
    positions = user_control.get_user_positions(user_id)

    # TODO: Convert to Position models
    return positions


@app.get("/api/pnl", response_model=Stats, tags=["trading"])
async def get_pnl(user_id: str = Depends(get_current_user)):
    """
    Get profit & loss statistics.

    Returns aggregated P&L without exposing strategy performance details.
    """
    stats = user_control.get_user_stats(user_id)

    return Stats(
        user_id=user_id,
        total_trades=stats.get('total_trades', 0),
        win_rate=stats.get('win_rate', 0.0),
        total_pnl=stats.get('total_pnl', 0.0),
        total_profit=stats.get('total_profit', 0.0),
        total_loss=stats.get('total_loss', 0.0),
        active_positions=stats.get('active_positions', 0)
    )


@app.get("/api/config", tags=["trading"])
async def get_config(user_id: str = Depends(get_current_user)):
    """
    Get user's trading configuration.

    Returns user settings and limits without exposing strategy parameters.
    """
    permissions = permission_validator.get_user_permissions(user_id)

    if not permissions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found"
        )

    return {
        "user_id": user_id,
        "max_position_size_usd": permissions.max_position_size_usd,
        "max_daily_loss_usd": permissions.max_daily_loss_usd,
        "max_positions": permissions.max_positions,
        "enabled": permissions.enabled
    }


# ========================================
# Analytics & Reporting Endpoints
# ========================================

@app.get("/api/analytics/trades", tags=["analytics"])
async def get_trade_history(
    user_id: str = Depends(get_current_user),
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Get trade history with pagination and date filtering.

    Args:
        limit: Number of trades to return (max 1000)
        offset: Offset for pagination
        start_date: ISO format start date (optional)
        end_date: ISO format end date (optional)
    """
    if limit > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit cannot exceed 1000"
        )

    # TODO: Implement actual trade history retrieval from database
    trades = user_control.get_user_trades(
        user_id=user_id,
        limit=limit,
        offset=offset,
        start_date=start_date,
        end_date=end_date
    )

    return {
        "user_id": user_id,
        "trades": trades,
        "count": len(trades),
        "limit": limit,
        "offset": offset
    }


@app.get("/api/analytics/performance", tags=["analytics"])
async def get_performance_metrics(
    user_id: str = Depends(get_current_user),
    period: str = "30d"
):
    """
    Get comprehensive performance metrics.

    Args:
        period: Time period (7d, 30d, 90d, 1y, all)
    """
    valid_periods = ['7d', '30d', '90d', '1y', 'all']
    if period not in valid_periods:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid period. Must be one of: {', '.join(valid_periods)}"
        )

    # TODO: Calculate actual metrics from database
    metrics = user_control.get_performance_metrics(user_id, period)

    return {
        "user_id": user_id,
        "period": period,
        "metrics": metrics or {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_trades": 0,
            "avg_trade_duration": "0h",
            "best_trade": 0.0,
            "worst_trade": 0.0
        }
    }


@app.get("/api/analytics/daily", tags=["analytics"])
async def get_daily_pnl(
    user_id: str = Depends(get_current_user),
    days: int = 30
):
    """
    Get daily P&L breakdown.

    Args:
        days: Number of days to retrieve (max 365)
    """
    if days > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Days cannot exceed 365"
        )

    # TODO: Get actual daily P&L from database
    daily_pnl = user_control.get_daily_pnl(user_id, days)

    return {
        "user_id": user_id,
        "days": days,
        "data": daily_pnl or []
    }


@app.get("/api/analytics/markets", tags=["analytics"])
async def get_market_breakdown(user_id: str = Depends(get_current_user)):
    """
    Get performance breakdown by market/pair.
    """
    # TODO: Get actual market breakdown from database
    breakdown = user_control.get_market_breakdown(user_id)

    return {
        "user_id": user_id,
        "markets": breakdown or []
    }



# ========================================
# Subscription & Billing Endpoints (Stripe)
# ========================================

_stripe_secret_key = os.getenv("STRIPE_SECRET_KEY", "")
_stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
_stripe_enabled = bool(_stripe_secret_key)
if _stripe_enabled:
    stripe.api_key = _stripe_secret_key
    logger.info("Stripe integration enabled")
else:
    logger.warning(
        "STRIPE_SECRET_KEY not set – Stripe endpoints will return mock responses. "
        "Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET to enable live billing."
    )

# Map subscription tier → Stripe Price IDs (configure via env vars)
_STRIPE_PRICES: Dict[str, str] = {
    "basic": os.getenv("STRIPE_PRICE_BASIC", ""),
    "pro": os.getenv("STRIPE_PRICE_PRO", ""),
    "enterprise": os.getenv("STRIPE_PRICE_ENTERPRISE", ""),
}

_TIER_FEATURES = {
    "basic":      {"max_position_size": 100,   "max_positions": 3},
    "pro":        {"max_position_size": 1000,  "max_positions": 10},
    "enterprise": {"max_position_size": 10000, "max_positions": 50},
}


class SubscriptionUpdate(BaseModel):
    tier: str = Field(..., pattern="^(basic|pro|enterprise)$")


@app.get("/api/subscription", tags=["subscription"])
async def get_subscription(user_id: str = Depends(get_current_user)):
    """Get current subscription details."""
    user_profile = user_db.get_user(user_id)

    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    tier = user_profile.get("subscription_tier", "basic")
    return {
        "user_id": user_id,
        "tier": tier,
        "status": "active",
        "next_billing_date": None,
        "features": _TIER_FEATURES.get(tier, _TIER_FEATURES["basic"]),
    }


@app.post("/api/subscription/checkout", tags=["subscription"])
async def create_checkout_session(
    request: Request,
    data: SubscriptionUpdate,
    user_id: str = Depends(get_current_user),
):
    """
    Create a Stripe Checkout Session for a new or upgraded subscription.

    Returns a checkout_url to redirect the user to the Stripe-hosted
    payment page.  In development mode (no Stripe key) returns a mock URL.
    """
    user_profile = user_db.get_user(user_id)
    if not user_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="User not found")

    if not _stripe_enabled:
        return {
            "checkout_url": f"https://checkout.stripe.com/mock?tier={data.tier}",
            "session_id": "mock_session",
            "mode": "mock",
            "message": "Stripe not configured – returning mock URL",
        }

    price_id = _STRIPE_PRICES.get(data.tier)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No Stripe price configured for tier '{data.tier}'. "
                   "Set STRIPE_PRICE_<TIER> environment variables.",
        )

    app_url = os.getenv("APP_BASE_URL", "https://app.nija.trading")
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=user_profile.get("email"),
            metadata={"user_id": user_id, "tier": data.tier},
            success_url=f"{app_url}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{app_url}/subscription/cancel",
        )
    except Exception as exc:
        logger.error(f"Stripe checkout creation failed for user {user_id}: {exc}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Payment service error. Please try again.")

    logger.info(f"Stripe checkout session created for user {user_id}, tier={data.tier}")
    return {
        "checkout_url": session.url,
        "session_id": session.id,
    }


@app.post("/api/subscription/upgrade", tags=["subscription"])
async def upgrade_subscription(
    request: Request,
    data: SubscriptionUpdate,
    user_id: str = Depends(get_current_user),
):
    """
    Initiate a subscription upgrade / downgrade.

    Redirects to Stripe Checkout for payment.  After successful payment,
    Stripe calls the webhook endpoint which updates the user's tier.
    """
    ip_address = request.client.host if request.client else ""
    old_tier = (user_db.get_user(user_id) or {}).get("subscription_tier", "basic")
    audit_log.subscription_changed(user_id=user_id, old_tier=old_tier,
                                   new_tier=data.tier, ip=ip_address)
    # Reuse checkout session creation logic
    return await create_checkout_session(request, data, user_id)


@app.post("/api/webhooks/stripe", tags=["subscription"], include_in_schema=False)
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events.

    Stripe signs every webhook payload – we verify the signature before
    processing to prevent spoofing.

    Configure your Stripe dashboard to send events to:
        POST /api/webhooks/stripe
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if _stripe_webhook_secret:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, _stripe_webhook_secret
            )
        except stripe.error.SignatureVerificationError:
            logger.warning("Stripe webhook signature verification failed")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # Accept unsigned events only in dev mode (no webhook secret configured)
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("type", "")
    data_obj = event.get("data", {}).get("object", {})

    logger.info(f"Stripe webhook received: {event_type}")
    audit_log.stripe_webhook(event_type=event_type,
                             customer_id=data_obj.get("customer", ""))

    if event_type == "checkout.session.completed":
        user_id = data_obj.get("metadata", {}).get("user_id")
        new_tier = data_obj.get("metadata", {}).get("tier")
        if user_id and new_tier:
            old_tier = (user_db.get_user(user_id) or {}).get("subscription_tier", "basic")
            user_db.update_subscription_tier(user_id=user_id, tier=new_tier)
            audit_log.subscription_changed(user_id=user_id, old_tier=old_tier,
                                           new_tier=new_tier)
            logger.info(f"Subscription updated via webhook: {user_id} → {new_tier}")

    elif event_type == "customer.subscription.deleted":
        # Subscription cancelled – downgrade user to free/basic tier
        customer_id = data_obj.get("customer", "")
        logger.warning(f"Subscription deleted for Stripe customer {customer_id}")
        # Note: implement customer_id → user_id lookup once Stripe customer IDs
        # are persisted per user (e.g. via a stripe_customers table).

    elif event_type == "invoice.payment_failed":
        customer_id = data_obj.get("customer", "")
        logger.warning(f"Payment failed for Stripe customer {customer_id}")

    return {"status": "ok"}


# ========================================
# Two-Factor Authentication (2FA) Endpoints
# ========================================

class TwoFASetupConfirm(BaseModel):
    code: str = Field(..., pattern="^[0-9]{6}$")


class TwoFAVerify(BaseModel):
    code: str = Field(..., min_length=6, max_length=10)
    method: str = Field(default="totp", pattern="^(totp|backup)$")


@app.post("/api/auth/2fa/setup", tags=["auth"])
async def setup_2fa(
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """
    Begin TOTP 2FA setup.

    Returns a QR code data URI and provisioning URI so the user can scan
    it with Google Authenticator (or any TOTP app).  Call
    POST /api/auth/2fa/confirm with the first code to activate.
    """
    user_profile = user_db.get_user(user_id)
    if not user_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="User not found")

    ip = request.client.host if request.client else ""
    audit_log.log("2fa_setup_start", user_id=user_id, ip_address=ip)

    result = two_fa.generate_setup(user_id=user_id, email=user_profile["email"])
    return result


@app.post("/api/auth/2fa/confirm", tags=["auth"])
async def confirm_2fa(
    body: TwoFASetupConfirm,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """
    Confirm 2FA setup by providing the first TOTP code.

    On success, 2FA is enabled and one-time backup codes are returned.
    Store the backup codes somewhere safe – they cannot be retrieved again.
    """
    ip = request.client.host if request.client else ""
    ok, backup_codes = two_fa.confirm_setup(user_id=user_id, code=body.code)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code. Ensure your authenticator app is synced."
        )

    audit_log.two_fa_enabled(user_id=user_id, ip=ip)
    return {
        "message": "2FA enabled successfully.",
        "backup_codes": backup_codes,
        "warning": "Save these backup codes securely. They will not be shown again.",
    }


@app.post("/api/auth/2fa/verify", tags=["auth"])
async def verify_2fa(
    body: TwoFAVerify,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """
    Verify a TOTP code or backup code.

    Used during login when 2FA is enabled (second factor step).
    """
    ip = request.client.host if request.client else ""

    if body.method == "backup":
        ok = two_fa.verify_backup_code(user_id=user_id, code=body.code)
    else:
        ok = two_fa.verify_totp(user_id=user_id, code=body.code)

    audit_log.two_fa_verify(user_id=user_id, ip=ip, success=ok,
                             method=body.method)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 2FA code"
        )
    return {"message": "2FA verified successfully."}


@app.delete("/api/auth/2fa", tags=["auth"])
async def disable_2fa(
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """Disable 2FA for the current user (requires re-authentication)."""
    ip = request.client.host if request.client else ""
    two_fa.disable(user_id=user_id)
    audit_log.two_fa_disabled(user_id=user_id, ip=ip)
    return {"message": "2FA disabled."}


@app.get("/api/auth/2fa/status", tags=["auth"])
async def get_2fa_status(user_id: str = Depends(get_current_user)):
    """Return whether 2FA is enabled for the current user."""
    return {"enabled": two_fa.is_enabled(user_id)}


@app.post("/api/auth/2fa/backup-codes/regenerate", tags=["auth"])
async def regenerate_backup_codes(
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """Regenerate backup codes (invalidates previous codes)."""
    codes = two_fa.regenerate_backup_codes(user_id=user_id)
    if codes is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled. Enable 2FA first."
        )
    ip = request.client.host if request.client else ""
    audit_log.log("2fa_backup_regenerated", user_id=user_id, ip_address=ip)
    return {
        "backup_codes": codes,
        "warning": "Old backup codes are now invalid. Save these securely.",
    }


# ========================================
# Email Verification Endpoints
# ========================================

class EmailVerifyToken(BaseModel):
    token: str


@app.post("/api/auth/email/send-verification", tags=["auth"])
async def send_email_verification(
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """
    (Re)send the verification email to the current user's address.

    The email contains a link valid for 24 hours.
    """
    user_profile = user_db.get_user(user_id)
    if not user_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="User not found")

    if user_profile.get("email_verified"):
        return {"message": "Email already verified."}

    try:
        email_svc.send_verification_email(user_id=user_id,
                                          email=user_profile["email"])
    except Exception as exc:
        logger.error(f"Failed to send verification email for {user_id}: {exc}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Could not send email. Please try again later.")

    ip = request.client.host if request.client else ""
    audit_log.log("email_verify_send", user_id=user_id, ip_address=ip)
    return {"message": "Verification email sent. Check your inbox."}


@app.post("/api/auth/email/verify", tags=["auth"])
async def verify_email(body: EmailVerifyToken, request: Request):
    """
    Verify an email address using the token from the verification email.

    This endpoint is called without authentication (the token IS the
    authentication for this single action).
    """
    verified_user_id = email_svc.verify_token(token=body.token, purpose="verify")
    if not verified_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token."
        )

    # Mark email as verified in the user database
    user_db.update_user(verified_user_id, {"email_verified": True})

    ip = request.client.host if request.client else ""
    audit_log.email_verified(user_id=verified_user_id, ip=ip)
    logger.info(f"Email verified for user {verified_user_id}")
    return {"message": "Email verified successfully. You can now log in."}


# ========================================
# Audit Log Endpoints (admin / self-service)
# ========================================

@app.get("/api/auth/audit-log", tags=["auth"])
async def get_my_audit_log(
    limit: int = 50,
    user_id: str = Depends(get_current_user),
):
    """Return recent security events for the authenticated user."""
    events = audit_log.get_recent_events(user_id=user_id, limit=min(limit, 200))
    return {"user_id": user_id, "events": events}

from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    """Manage WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = defaultdict(list)

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id].append(websocket)
        logger.info(f"📡 WebSocket connected for user {user_id}")

    def disconnect(self, user_id: str, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            logger.info(f"📡 WebSocket disconnected for user {user_id}")

    async def send_personal_message(self, user_id: str, message: Dict[str, Any]):
        """Send message to specific user's connections."""
        for connection in self.active_connections.get(user_id, []):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send WebSocket message: {e}")

manager = ConnectionManager()


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for real-time trading updates.

    Sends real-time notifications for:
    - Trade executions
    - Position updates
    - P&L changes
    - System alerts
    """
    await manager.connect(user_id, websocket)
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()

            # Echo back for now (placeholder)
            await websocket.send_json({
                "type": "ack",
                "message": "Message received",
                "timestamp": datetime.utcnow().isoformat()
            })
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)


# ========================================
# Static Files & Frontend (if needed)
# ========================================

# Mount static files if frontend directory exists
frontend_dir = os.path.join(os.path.dirname(__file__), 'frontend')
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=os.path.join(frontend_dir, 'static')), name="static")

    @app.get("/")
    async def serve_frontend():
        """Serve frontend index.html"""
        return FileResponse(os.path.join(frontend_dir, 'templates', 'index.html'))


# ========================================
# Startup Event
# ========================================

@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    logger.info("=" * 60)
    logger.info("🚀 NIJA Platform - FastAPI Backend Starting")
    logger.info("=" * 60)
    logger.info("Stack: FastAPI + PostgreSQL + Redis + Docker")
    logger.info("Architecture: NIJA as Headless Microservice")
    logger.info("=" * 60)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv('PORT', 8000))

    uvicorn.run(
        "fastapi_backend:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv('DEBUG', 'false').lower() == 'true'
    )
