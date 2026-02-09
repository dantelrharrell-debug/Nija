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
    from position_source_constants import PositionSource, get_source_label, is_nija_managed
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
    # Fallback for position source utils
    def get_source_label(source):
        return "Unknown Source"
    def is_nija_managed(pos):
        return pos.get('position_source') == 'nija_strategy'

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
    # Position source tracking (Feb 8, 2026)
    position_source: Optional[str] = 'unknown'  # Use PositionSource enum values
    managed_by_nija: Optional[bool] = None  # Computed field for convenience
    source_label: Optional[str] = None  # Human-readable label


class PositionsResponse(BaseModel):
    """Response model for positions endpoint"""
    success: bool
    positions: List[Position]
    total_positions: int
    total_unrealized_pnl: Optional[float] = None
    # Position breakdown by source (Feb 8, 2026)
    nija_managed_count: Optional[int] = None
    existing_holdings_count: Optional[int] = None
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
        PositionsResponse: List of active positions with P&L and source labels
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

        # Convert to Position models with source tracking
        positions = []
        nija_managed_count = 0
        existing_holdings_count = 0
        
        for pos in positions_data:
            position_source = pos.get('position_source', 'unknown')
            managed_by_nija = is_nija_managed(pos)
            
            # Track counts
            if managed_by_nija:
                nija_managed_count += 1
            else:
                existing_holdings_count += 1
            
            positions.append(Position(
                pair=pos.get('pair', 'UNKNOWN'),
                side=pos.get('side', 'long'),
                size=pos.get('size', 0.0),
                entry_price=pos.get('entry_price', 0.0),
                current_price=pos.get('current_price'),
                unrealized_pnl=pos.get('unrealized_pnl'),
                unrealized_pnl_percent=pos.get('unrealized_pnl_percent'),
                stop_loss=pos.get('stop_loss'),
                take_profit=pos.get('take_profit'),
                opened_at=pos.get('opened_at'),
                position_source=position_source,
                managed_by_nija=managed_by_nija,
                source_label=get_source_label(position_source)
            ))

        # Calculate total P&L
        total_pnl = sum(p.unrealized_pnl for p in positions if p.unrealized_pnl is not None)

        return PositionsResponse(
            success=True,
            positions=positions,
            total_positions=len(positions),
            nija_managed_count=nija_managed_count,
            existing_holdings_count=existing_holdings_count,
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
# Position Reduction Endpoints
# ========================================

class PositionComplianceResponse(BaseModel):
    """Response model for position compliance check"""
    success: bool
    user_id: str
    broker_type: str
    current_positions: int
    max_positions: int
    dust_positions: int
    excess_positions: int
    compliant: bool
    preview: Optional[Dict] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PositionReductionResponse(BaseModel):
    """Response model for position reduction"""
    success: bool
    user_id: str
    broker_type: str
    initial_positions: int
    final_positions: int
    closed_positions: int
    breakdown: Dict
    outcomes: Dict
    capital_impact: Dict
    dry_run: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class AdminEnforceAllResponse(BaseModel):
    """Response model for admin enforce all users"""
    success: bool
    total_users: int
    users_processed: int
    total_positions_closed: int
    results: List[Dict]
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# Import position reduction engine
try:
    from bot.user_position_reduction_engine import UserPositionReductionEngine
    from bot.multi_account_broker_manager import MultiAccountBrokerManager
    from bot.portfolio_state import PortfolioStateManager
    
    # Initialize global instances (lazy initialization)
    _reduction_engine = None
    
    def get_reduction_engine():
        """Get or create position reduction engine instance"""
        global _reduction_engine
        if _reduction_engine is None:
            # Get broker and portfolio managers from environment
            broker_mgr = MultiAccountBrokerManager()
            portfolio_mgr = PortfolioStateManager()
            
            _reduction_engine = UserPositionReductionEngine(
                multi_account_broker_manager=broker_mgr,
                portfolio_state_manager=portfolio_mgr,
                trade_ledger=None  # Optional
            )
        return _reduction_engine
        
except ImportError as e:
    logger.warning(f"Position reduction imports not available: {e}")
    def get_reduction_engine():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Position reduction feature not available"
        )


@app.get("/api/v1/users/{user_id}/position-compliance", response_model=PositionComplianceResponse)
async def get_position_compliance(
    user_id: str,
    broker_type: str = "kraken",
    current_user: str = Depends(get_current_user)
):
    """
    Get position compliance status for a user.
    
    Shows current position count, dust positions, excess positions,
    and what would be closed if enforcement runs.
    
    This is a read-only endpoint that doesn't modify positions.
    """
    try:
        # Verify user has permission
        if current_user != user_id and current_user != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this user's compliance"
            )
        
        engine = get_reduction_engine()
        
        # Get current positions
        positions = engine.get_user_positions(user_id, broker_type)
        current_count = len(positions)
        
        # Identify what would be closed
        dust = engine.identify_dust_positions(positions)
        remaining = [p for p in positions if p['size_usd'] >= engine.dust_threshold_usd]
        excess = engine.identify_cap_excess_positions(remaining)
        
        # Check compliance
        compliant = (
            len(dust) == 0 and
            len(remaining) <= engine.max_positions
        )
        
        return PositionComplianceResponse(
            success=True,
            user_id=user_id,
            broker_type=broker_type,
            current_positions=current_count,
            max_positions=engine.max_positions,
            dust_positions=len(dust),
            excess_positions=len(excess),
            compliant=compliant,
            preview={
                'dust_positions': [
                    {'symbol': p['symbol'], 'size_usd': p['size_usd'], 'pnl_pct': p['pnl_pct']}
                    for p in dust
                ],
                'excess_positions': [
                    {'symbol': p['symbol'], 'size_usd': p['size_usd'], 'pnl_pct': p['pnl_pct']}
                    for p in excess
                ]
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking compliance for {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking compliance: {str(e)}"
        )


@app.post("/api/v1/users/{user_id}/reduce-positions", response_model=PositionReductionResponse)
async def reduce_user_positions(
    user_id: str,
    broker_type: str = "kraken",
    max_positions: Optional[int] = None,
    dust_threshold_usd: Optional[float] = None,
    current_user: str = Depends(get_current_user)
):
    """
    Manually trigger position reduction for a user.
    
    This will actually close positions to enforce limits.
    Returns list of closed positions with outcomes.
    """
    try:
        # Verify user has permission
        if current_user != user_id and current_user != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to reduce this user's positions"
            )
        
        engine = get_reduction_engine()
        
        # Execute reduction
        result = engine.reduce_user_positions(
            user_id=user_id,
            broker_type=broker_type,
            dry_run=False,
            max_positions=max_positions,
            dust_threshold_usd=dust_threshold_usd
        )
        
        return PositionReductionResponse(
            success=True,
            user_id=result['user_id'],
            broker_type=result['broker_type'],
            initial_positions=result['initial_positions'],
            final_positions=result['final_positions'],
            closed_positions=result['closed_positions'],
            breakdown=result['breakdown'],
            outcomes=result['outcomes'],
            capital_impact=result['capital_impact'],
            dry_run=result.get('dry_run', False)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reducing positions for {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reducing positions: {str(e)}"
        )


@app.get("/api/v1/users/{user_id}/reduction-preview", response_model=PositionReductionResponse)
async def preview_position_reduction(
    user_id: str,
    broker_type: str = "kraken",
    max_positions: Optional[int] = None,
    dust_threshold_usd: Optional[float] = None,
    current_user: str = Depends(get_current_user)
):
    """
    Preview position reduction for a user (dry-run).
    
    Shows what positions would be closed without actually closing them.
    This is a safe read-only operation.
    """
    try:
        # Verify user has permission
        if current_user != user_id and current_user != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this user's reduction preview"
            )
        
        engine = get_reduction_engine()
        
        # Run preview (dry-run)
        result = engine.preview_reduction(
            user_id=user_id,
            broker_type=broker_type,
            max_positions=max_positions,
            dust_threshold_usd=dust_threshold_usd
        )
        
        return PositionReductionResponse(
            success=True,
            user_id=result['user_id'],
            broker_type=result['broker_type'],
            initial_positions=result['initial_positions'],
            final_positions=result['final_positions'],
            closed_positions=result['closed_positions'],
            breakdown=result['breakdown'],
            outcomes=result['outcomes'],
            capital_impact=result['capital_impact'],
            dry_run=True
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error previewing reduction for {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error previewing reduction: {str(e)}"
        )


@app.post("/api/v1/admin/enforce-all-users", response_model=AdminEnforceAllResponse)
async def enforce_all_users(
    broker_type: str = "kraken",
    current_user: str = Depends(get_current_user)
):
    """
    Admin endpoint to trigger position enforcement across ALL users.
    
    This requires admin privileges.
    Returns summary of actions taken per user.
    """
    try:
        # Verify admin permission
        if current_user != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges required"
            )
        
        # Load user configs
        import json
        import os
        
        config_dir = os.path.join(os.path.dirname(__file__), 'config', 'users')
        user_configs = []
        
        if os.path.exists(config_dir):
            for filename in os.listdir(config_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(config_dir, filename)
                    try:
                        with open(filepath, 'r') as f:
                            config = json.load(f)
                            if 'user_id' not in config:
                                config['user_id'] = filename.replace('.json', '')
                            user_configs.append(config)
                    except Exception as e:
                        logger.warning(f"Failed to load config {filename}: {e}")
        
        engine = get_reduction_engine()
        results = []
        total_closed = 0
        
        # Process each user
        for config in user_configs:
            if not config.get('enabled', False):
                continue
            
            user_id = config.get('user_id')
            user_broker_type = config.get('broker', config.get('broker_type', broker_type))
            
            try:
                result = engine.reduce_user_positions(
                    user_id=user_id,
                    broker_type=user_broker_type,
                    dry_run=False
                )
                
                results.append({
                    'user_id': user_id,
                    'success': True,
                    'closed_positions': result.get('closed_positions', 0),
                    'initial_positions': result.get('initial_positions', 0),
                    'final_positions': result.get('final_positions', 0)
                })
                
                total_closed += result.get('closed_positions', 0)
            
            except Exception as e:
                logger.error(f"Error enforcing for {user_id}: {e}")
                results.append({
                    'user_id': user_id,
                    'success': False,
                    'error': str(e)
                })
        
        return AdminEnforceAllResponse(
            success=True,
            total_users=len(user_configs),
            users_processed=len(results),
            total_positions_closed=total_closed,
            results=results
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in admin enforce all: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error enforcing all users: {str(e)}"
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
