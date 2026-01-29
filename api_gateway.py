"""
NIJA API Gateway - Public Trading Control Interface

This is the API layer that exposes trading engine controls to mobile and web applications.
It provides essential endpoints for managing trading, monitoring positions, and tracking performance.

Endpoints:
- POST   /api/v1/start       - Start the trading engine
- POST   /api/v1/stop        - Stop the trading engine
- GET    /api/v1/balance     - Get current account balance
- GET    /api/v1/positions   - Get active positions
- GET    /api/v1/performance - Get trading performance metrics

Security:
- JWT-based authentication
- CORS enabled for mobile apps
- Rate limiting (optional)
- User isolation

Architecture:
  [ iOS/Android/Web Apps ]
            ↓
  [ API Gateway ] ← YOU ARE HERE (api_gateway.py)
            ↓
  [ User Control Backend ] (user_control.py)
            ↓
  [ Trading Engine ] (bot.py + v7.2 strategy)
            ↓
  [ Exchanges ]
"""

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import jwt
import os
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add bot directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import authentication and user control
try:
    from auth import get_api_key_manager, get_user_manager
    from execution import get_permission_validator, UserPermissions
    from user_control import get_user_control_backend
except ImportError as e:
    logger.warning(f"Import warning: {e}. Some features may not be available.")
    # Define fallback stubs
    def get_api_key_manager():
        return None
    def get_user_manager():
        return None
    def get_permission_validator():
        return None
    def get_user_control_backend():
        return None

# Import broker manager for balance queries
try:
    from bot.broker_manager import get_broker_manager
except ImportError:
    try:
        from broker_manager import get_broker_manager
    except ImportError:
        logger.warning("broker_manager not available. Balance endpoint will use mock data.")
        def get_broker_manager(*args, **kwargs):
            return None

# Initialize FastAPI app
app = FastAPI(
    title="NIJA Trading API Gateway",
    description="API for controlling the NIJA autonomous trading bot (v7.2 Strategy Locked)",
    version="1.0.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc"
)

# CORS configuration
allowed_origins = os.getenv('ALLOWED_ORIGINS', '*')
if allowed_origins == '*':
    logger.warning("⚠️  SECURITY WARNING: CORS is configured to allow ALL origins (*)")
    logger.warning("⚠️  For production, set ALLOWED_ORIGINS environment variable")
    logger.warning("⚠️  Example: ALLOWED_ORIGINS=https://app.example.com,https://mobile.example.com")
    logger.warning("⚠️  Disabling credentials for wildcard CORS (security requirement)")

# Parse origins from comma-separated string or use wildcard
origins_list = allowed_origins.split(',') if allowed_origins != '*' else ["*"]

# When using wildcard origins, credentials must be disabled for security
allow_credentials = allowed_origins != '*'

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins_list,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
if not JWT_SECRET_KEY:
    logger.critical("🔒 SECURITY WARNING: JWT_SECRET_KEY environment variable not set!")
    logger.critical("🔒 Please set JWT_SECRET_KEY to a secure random value before deploying.")
    logger.critical("🔒 Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'")
    # Exit immediately if no JWT secret is configured
    sys.exit(1)

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))

# Get manager instances
user_control = get_user_control_backend()
permission_validator = get_permission_validator()

# Security
security = HTTPBearer()

# ========================================
# Pydantic Models (Request/Response)
# ========================================

class TradingControlRequest(BaseModel):
    """Request model for start/stop trading"""
    pass  # No additional parameters needed


class TradingControlResponse(BaseModel):
    """Response model for start/stop trading"""
    success: bool
    message: str
    status: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class BalanceResponse(BaseModel):
    """Response model for balance endpoint"""
    success: bool
    balance: float
    currency: str = "USD"
    available_for_trading: Optional[float] = None
    broker: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Position(BaseModel):
    """Model for a single trading position"""
    pair: str
    side: str  # 'long' or 'short'
    size: float
    entry_price: float
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_percent: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[str] = None


class PositionsResponse(BaseModel):
    """Response model for positions endpoint"""
    success: bool
    positions: List[Position]
    total_positions: int
    total_unrealized_pnl: Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PerformanceMetrics(BaseModel):
    """Model for trading performance metrics"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    profit_factor: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    active_positions: int = 0


class PerformanceResponse(BaseModel):
    """Response model for performance endpoint"""
    success: bool
    metrics: PerformanceMetrics
    period: str = "all_time"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ========================================
# Helper Functions
# ========================================

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

    user_id = payload.get('user_id')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id


# ========================================
# API Endpoints
# ========================================

@app.get("/")
async def root():
    """Root endpoint - API information"""
    return {
        "name": "NIJA Trading API Gateway",
        "version": "1.0.0",
        "strategy": "v7.2 (Locked - Profitability Mode)",
        "status": "operational",
        "docs": "/api/v1/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/v1/start", response_model=TradingControlResponse)
async def start_trading(
    request: TradingControlRequest,
    user_id: str = Depends(get_current_user)
):
    """
    Start the trading engine for the authenticated user.

    This endpoint:
    1. Validates user permissions
    2. Initializes trading engine with v7.2 strategy
    3. Connects to configured exchanges
    4. Begins autonomous trading

    Returns:
        TradingControlResponse: Success status and current engine state
    """
    try:
        logger.info(f"📊 Start trading request from user {user_id}")

        if not user_control:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="User control backend not available"
            )

        # Start trading via user control backend
        result = user_control.start_trading(user_id)

        if not result.get('success', False):
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"❌ Failed to start trading for user {user_id}: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        logger.info(f"✅ Trading started for user {user_id}")

        return TradingControlResponse(
            success=True,
            message="Trading engine started successfully",
            status=result.get('status', 'running')
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔥 Error starting trading for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error. Please try again later."
        )


@app.post("/api/v1/stop", response_model=TradingControlResponse)
async def stop_trading(
    request: TradingControlRequest,
    user_id: str = Depends(get_current_user)
):
    """
    Stop the trading engine for the authenticated user.

    This endpoint:
    1. Gracefully closes all open positions
    2. Cancels pending orders
    3. Stops the trading engine
    4. Preserves state for later resumption

    Returns:
        TradingControlResponse: Success status and current engine state
    """
    try:
        logger.info(f"🛑 Stop trading request from user {user_id}")

        if not user_control:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="User control backend not available"
            )

        # Stop trading via user control backend
        result = user_control.stop_trading(user_id)

        if not result.get('success', False):
            error_msg = result.get('error', result.get('message', 'Unknown error'))
            logger.error(f"❌ Failed to stop trading for user {user_id}: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        logger.info(f"✅ Trading stopped for user {user_id}")

        return TradingControlResponse(
            success=True,
            message="Trading engine stopped successfully",
            status=result.get('status', 'stopped')
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔥 Error stopping trading for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error. Please try again later."
        )


@app.get("/api/v1/balance", response_model=BalanceResponse)
async def get_balance(
    user_id: str = Depends(get_current_user)
):
    """
    Get current account balance for the authenticated user.

    Returns:
        BalanceResponse: Current balance and available capital for trading
    """
    try:
        logger.info(f"💰 Balance request from user {user_id}")

        # TODO: Integrate with actual broker balance query
        # This endpoint is not yet fully implemented
        logger.warning(f"⚠️  Balance endpoint called but returning mock data for user {user_id}")

        # Return mock data with clear indication
        mock_balance = 1000.0

        return BalanceResponse(
            success=True,
            balance=mock_balance,
            currency="USD",
            available_for_trading=mock_balance * 0.95,
            broker="Mock (Not Connected)"  # Clear indicator this is mock data
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔥 Error fetching balance for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error. Please try again later."
        )


@app.get("/api/v1/positions", response_model=PositionsResponse)
async def get_positions(
    user_id: str = Depends(get_current_user)
):
    """
    Get all active positions for the authenticated user.

    Returns:
        PositionsResponse: List of active positions with P&L
    """
    try:
        logger.info(f"📈 Positions request from user {user_id}")

        if not user_control:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="User control backend not available"
            )

        # Get positions from user control backend
        instance = user_control.get_or_create_instance(user_id)
        positions_data = instance.get_positions()

        # Convert to Position models
        positions = [
            Position(
                pair=pos.get('pair', 'UNKNOWN'),
                side=pos.get('side', 'long'),
                size=pos.get('size', 0.0),
                entry_price=pos.get('entry_price', 0.0),
                current_price=pos.get('current_price'),
                unrealized_pnl=pos.get('unrealized_pnl'),
                unrealized_pnl_percent=pos.get('unrealized_pnl_percent'),
                stop_loss=pos.get('stop_loss'),
                take_profit=pos.get('take_profit'),
                opened_at=pos.get('opened_at')
            )
            for pos in positions_data
        ]

        # Calculate total P&L
        total_pnl = sum(p.unrealized_pnl for p in positions if p.unrealized_pnl is not None)

        return PositionsResponse(
            success=True,
            positions=positions,
            total_positions=len(positions),
            total_unrealized_pnl=total_pnl if positions else None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔥 Error fetching positions for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error. Please try again later."
        )


@app.get("/api/v1/performance", response_model=PerformanceResponse)
async def get_performance(
    user_id: str = Depends(get_current_user),
    period: str = "all_time"
):
    """
    Get trading performance metrics for the authenticated user.

    Args:
        period: Time period for metrics (all_time, 30d, 7d, 24h)

    Returns:
        PerformanceResponse: Comprehensive trading performance metrics
    """
    try:
        logger.info(f"📊 Performance request from user {user_id} (period: {period})")

        if not user_control:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="User control backend not available"
            )

        # Get stats from user control backend
        instance = user_control.get_or_create_instance(user_id)
        stats = instance.get_stats()

        # Calculate derived metrics
        total_trades = stats.get('total_trades', 0)
        winning_trades = stats.get('winning_trades', 0)
        losing_trades = stats.get('losing_trades', 0)

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        total_profit = stats.get('total_profit', 0.0)
        total_loss = abs(stats.get('total_loss', 0.0))

        avg_win = (total_profit / winning_trades) if winning_trades > 0 else 0.0
        avg_loss = (total_loss / losing_trades) if losing_trades > 0 else 0.0

        profit_factor = (total_profit / total_loss) if total_loss > 0 else None

        metrics = PerformanceMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=stats.get('total_pnl', 0.0),
            total_profit=total_profit,
            total_loss=total_loss,
            average_win=avg_win,
            average_loss=avg_loss,
            profit_factor=profit_factor,
            active_positions=stats.get('active_positions', 0)
        )

        return PerformanceResponse(
            success=True,
            metrics=metrics,
            period=period
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔥 Error fetching performance for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error. Please try again later."
        )


# ========================================
# Main Entry Point
# ========================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))

    logger.info("=" * 80)
    logger.info("🚀 NIJA API Gateway Starting")
    logger.info("=" * 80)
    logger.info(f"📡 Listening on port {port}")
    logger.info(f"📚 API Docs: http://localhost:{port}/api/v1/docs")
    logger.info(f"🔒 Strategy: v7.2 (Locked - Profitability Mode)")
    logger.info("=" * 80)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
