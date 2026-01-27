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

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import jwt
import hashlib
import secrets
import os
import logging

from auth import get_api_key_manager, get_user_manager
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
    redoc_url="/api/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))

# Get manager instances
api_key_manager = get_api_key_manager()
user_manager = get_user_manager()
permission_validator = get_permission_validator()
user_control = get_user_control_backend()

# Security
security = HTTPBearer()

# In-memory user credentials (TODO: replace with PostgreSQL)
user_credentials = {}


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

def hash_password(password: str) -> str:
    """Hash password using SHA256 (TODO: upgrade to bcrypt)."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return hash_password(password) == password_hash


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


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
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
    
    return payload['user_id']


# ========================================
# Health & Info Endpoints
# ========================================

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "NIJA FastAPI Backend",
        "version": "2.0.0"
    }


@app.get("/api/info")
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

@app.post("/api/auth/register", response_model=TokenResponse)
async def register(user_data: UserRegister):
    """
    Register a new user account.
    
    Returns JWT token for immediate login.
    """
    email = user_data.email.lower().strip()
    
    # Check if user exists
    if email in user_credentials:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists"
        )
    
    # Create user ID
    user_id = f"user_{secrets.token_hex(8)}"
    
    # Store credentials
    user_credentials[email] = {
        'password_hash': hash_password(user_data.password),
        'user_id': user_id
    }
    
    # Create user profile
    user_profile = user_manager.create_user(
        user_id=user_id,
        email=email,
        subscription_tier=user_data.subscription_tier
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
    
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        email=email,
        subscription_tier=user_data.subscription_tier
    )


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """
    Login user and return JWT token.
    """
    email = credentials.email.lower().strip()
    
    # Check credentials
    if email not in user_credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    user_creds = user_credentials[email]
    
    if not verify_password(credentials.password, user_creds['password_hash']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    user_id = user_creds['user_id']
    user_profile = user_manager.get_user(user_id)
    
    if not user_profile or not user_profile.get('enabled', True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled"
        )
    
    # Generate token
    token = create_access_token(user_id)
    
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

@app.get("/api/user/profile", response_model=UserProfile)
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

@app.get("/api/user/brokers")
async def list_brokers(user_id: str = Depends(get_current_user)):
    """List all configured brokers for user."""
    brokers = api_key_manager.list_user_brokers(user_id)
    return {"user_id": user_id, "brokers": brokers, "count": len(brokers)}


@app.post("/api/user/brokers/{broker_name}")
async def add_broker(
    broker_name: str,
    credentials: BrokerCredentials,
    user_id: str = Depends(get_current_user)
):
    """Add broker API credentials."""
    supported_brokers = ['coinbase', 'kraken', 'binance', 'okx', 'alpaca']
    
    if broker_name.lower() not in supported_brokers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported broker. Supported: {', '.join(supported_brokers)}"
        )
    
    # Store encrypted credentials
    api_key_manager.store_user_api_key(
        user_id=user_id,
        broker=broker_name.lower(),
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
        additional_params=credentials.additional_params
    )
    
    logger.info(f"✅ User {user_id} added {broker_name} credentials")
    
    return {"message": f"{broker_name} credentials added successfully", "broker": broker_name}


@app.delete("/api/user/brokers/{broker_name}")
async def remove_broker(broker_name: str, user_id: str = Depends(get_current_user)):
    """Remove broker API credentials."""
    success = api_key_manager.delete_user_api_key(user_id, broker_name.lower())
    
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

@app.post("/api/start_bot")
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


@app.post("/api/stop_bot")
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


@app.get("/api/status", response_model=TradingStatus)
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


@app.get("/api/positions", response_model=List[Position])
async def get_positions(user_id: str = Depends(get_current_user)):
    """
    Get active trading positions.
    
    Returns current positions without exposing entry/exit logic.
    """
    positions = user_control.get_user_positions(user_id)
    
    # TODO: Convert to Position models
    return positions


@app.get("/api/pnl", response_model=Stats)
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


@app.get("/api/config")
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
