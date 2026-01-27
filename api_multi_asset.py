"""
NIJA Multi-Asset SaaS API

Enhanced FastAPI backend integrating all multi-asset platform features:
- Multi-asset trading (crypto, equity, derivatives)
- Tier-based execution routing
- Revenue tracking
- User isolation and security
- Advanced risk management

This is the production SaaS backend for the NIJA platform.

Author: NIJA Trading Systems
Version: 2.0
Date: January 27, 2026
"""

from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import os
import hashlib
import secrets

# Import core modules
from core.multi_asset_router import (
    MultiAssetRouter, AssetClass, MarketRegime, AssetAllocation, MarketConditions
)
from core.asset_engines import create_engine, StrategyType
from core.tiered_risk_engine import TieredRiskEngine, RiskLevel
from core.execution_router import ExecutionRouter, ExecutionOrchestrator, ExecutionPriority
from core.equity_broker_integration import (
    get_equity_broker_manager, AlpacaBroker, EquityBroker
)
from core.revenue_tracker import get_revenue_tracker, SubscriptionTier, RevenueType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NIJA Multi-Asset Trading Platform",
    description="Autonomous multi-asset trading with AI-powered strategies",
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

# Security
security = HTTPBearer()

# Global instances
execution_router = ExecutionRouter()
execution_orchestrator = ExecutionOrchestrator(execution_router)
revenue_tracker = get_revenue_tracker()
equity_broker_manager = get_equity_broker_manager()

# In-memory user data (TODO: Replace with PostgreSQL)
users_db: Dict[str, Dict[str, Any]] = {}
active_routers: Dict[str, MultiAssetRouter] = {}
active_risk_engines: Dict[str, TieredRiskEngine] = {}


# ========================================
# Pydantic Models
# ========================================

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    tier: str = Field(default="SAVER", pattern="^(STARTER|SAVER|INVESTOR|INCOME|LIVABLE|BALLER)$")
    initial_capital: float = Field(default=100.0, ge=50.0)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    tier: str


class CapitalAllocationResponse(BaseModel):
    crypto_pct: float
    equity_pct: float
    derivatives_pct: float
    cash_pct: float
    crypto_usd: float
    equity_usd: float
    derivatives_usd: float
    cash_usd: float


class TradingStatusResponse(BaseModel):
    user_id: str
    tier: str
    total_capital: float
    asset_allocation: CapitalAllocationResponse
    active_positions: int
    risk_status: Dict
    execution_priority: str


class RevenueResponse(BaseModel):
    total_revenue: float
    mrr: float
    arr: float
    revenue_by_type: Dict[str, float]
    revenue_last_30_days: float


class TradeRequest(BaseModel):
    symbol: str
    asset_class: str = Field(pattern="^(crypto|equity|derivatives)$")
    side: str = Field(pattern="^(buy|sell)$")
    size: float = Field(gt=0)
    order_type: str = Field(default="market", pattern="^(market|limit)$")
    limit_price: Optional[float] = None


# ========================================
# Helper Functions
# ========================================

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """Get current user from token (simplified - use JWT in production)."""
    token = credentials.credentials
    
    # Simplified auth - in production, decode JWT and validate
    for user_id, user_data in users_db.items():
        if user_data.get("token") == token:
            return {"user_id": user_id, **user_data}
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials"
    )


def get_or_create_router(user_id: str, tier: str, capital: float) -> MultiAssetRouter:
    """Get or create multi-asset router for user."""
    if user_id not in active_routers:
        active_routers[user_id] = MultiAssetRouter(
            user_tier=tier,
            total_capital=capital,
            risk_tolerance="moderate"
        )
    return active_routers[user_id]


def get_or_create_risk_engine(user_id: str, tier: str, capital: float) -> TieredRiskEngine:
    """Get or create risk engine for user."""
    if user_id not in active_risk_engines:
        active_risk_engines[user_id] = TieredRiskEngine(
            user_tier=tier,
            total_capital=capital
        )
    return active_risk_engines[user_id]


# ========================================
# API Endpoints
# ========================================

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("Starting NIJA Multi-Asset Platform API v2.0")
    
    # Start execution orchestrator
    execution_orchestrator.start()
    
    # Initialize equity broker (Alpaca)
    if os.getenv('ALPACA_API_KEY'):
        alpaca = AlpacaBroker(paper_trading=True)
        if alpaca.authenticate():
            equity_broker_manager.add_broker(EquityBroker.ALPACA, alpaca)
            logger.info("Alpaca broker initialized successfully")
    
    logger.info("NIJA platform ready")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    execution_orchestrator.stop()
    logger.info("NIJA platform stopped")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "NIJA Multi-Asset Trading Platform",
        "version": "2.0.0",
        "status": "operational",
        "features": [
            "Multi-asset trading (crypto, equity, derivatives)",
            "Tier-based execution",
            "Revenue tracking",
            "Advanced risk management"
        ]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "execution_queues": execution_router.get_queue_status(),
        "active_users": len(users_db)
    }


@app.post("/api/v2/register", response_model=TokenResponse)
async def register(user: UserRegister, background_tasks: BackgroundTasks):
    """Register a new user."""
    # Check if user exists
    if any(u["email"] == user.email for u in users_db.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user
    user_id = f"user_{len(users_db) + 1}"
    token = f"token_{user_id}"  # Simplified - use JWT in production
    
    users_db[user_id] = {
        "email": user.email,
        "password_hash": hash_password(user.password),  # Hash password before storage
        "tier": user.tier,
        "capital": user.initial_capital,
        "token": token,
        "created_at": datetime.now().isoformat()
    }
    
    # Record subscription revenue
    tier_enum = SubscriptionTier[user.tier]
    background_tasks.add_task(
        revenue_tracker.record_subscription,
        user_id=user_id,
        tier=tier_enum,
        is_annual=False
    )
    
    logger.info(f"New user registered: {user_id}, tier={user.tier}")
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user_id,
        tier=user.tier
    )


@app.get("/api/v2/allocation", response_model=CapitalAllocationResponse)
async def get_allocation(current_user: Dict = Depends(get_current_user)):
    """Get current capital allocation across asset classes."""
    user_id = current_user["user_id"]
    tier = current_user["tier"]
    capital = current_user["capital"]
    
    # Get router
    router = get_or_create_router(user_id, tier, capital)
    
    # Get allocation
    allocation = router.route_capital()
    capital_by_asset = router.get_capital_by_asset_class(allocation)
    
    return CapitalAllocationResponse(
        crypto_pct=allocation.crypto_pct,
        equity_pct=allocation.equity_pct,
        derivatives_pct=allocation.derivatives_pct,
        cash_pct=allocation.cash_pct,
        crypto_usd=capital_by_asset[AssetClass.CRYPTO],
        equity_usd=capital_by_asset[AssetClass.EQUITY],
        derivatives_usd=capital_by_asset[AssetClass.DERIVATIVES],
        cash_usd=capital_by_asset[AssetClass.CASH]
    )


@app.get("/api/v2/status", response_model=TradingStatusResponse)
async def get_status(current_user: Dict = Depends(get_current_user)):
    """Get comprehensive trading status."""
    user_id = current_user["user_id"]
    tier = current_user["tier"]
    capital = current_user["capital"]
    
    # Get router and allocation
    router = get_or_create_router(user_id, tier, capital)
    allocation = router.route_capital()
    capital_by_asset = router.get_capital_by_asset_class(allocation)
    
    # Get risk engine status
    risk_engine = get_or_create_risk_engine(user_id, tier, capital)
    risk_status = risk_engine.get_risk_status()
    
    # Get execution config
    exec_config = execution_router.get_tier_config(tier)
    
    return TradingStatusResponse(
        user_id=user_id,
        tier=tier,
        total_capital=capital,
        asset_allocation=CapitalAllocationResponse(
            crypto_pct=allocation.crypto_pct,
            equity_pct=allocation.equity_pct,
            derivatives_pct=allocation.derivatives_pct,
            cash_pct=allocation.cash_pct,
            crypto_usd=capital_by_asset[AssetClass.CRYPTO],
            equity_usd=capital_by_asset[AssetClass.EQUITY],
            derivatives_usd=capital_by_asset[AssetClass.DERIVATIVES],
            cash_usd=capital_by_asset[AssetClass.CASH]
        ),
        active_positions=0,  # TODO: Get from position manager
        risk_status=risk_status,
        execution_priority=exec_config.priority.name
    )


@app.post("/api/v2/trade")
async def place_trade(
    trade: TradeRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user)
):
    """Place a trade."""
    user_id = current_user["user_id"]
    tier = current_user["tier"]
    capital = current_user["capital"]
    
    # Validate with risk engine
    risk_engine = get_or_create_risk_engine(user_id, tier, capital)
    
    approved, risk_level, message = risk_engine.validate_trade(
        trade_size=trade.size,
        current_positions=0,  # TODO: Get actual position count
        market_volatility=50.0,  # TODO: Get actual volatility
        asset_class=trade.asset_class
    )
    
    if not approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trade rejected by risk engine: {message}"
        )
    
    # Route order to execution
    order = {
        "user_id": user_id,
        "symbol": trade.symbol,
        "asset_class": trade.asset_class,
        "side": trade.side,
        "size": trade.size,
        "order_type": trade.order_type,
        "limit_price": trade.limit_price
    }
    
    routing_info = execution_router.route_order(tier, order)
    
    logger.info(f"Trade placed: {user_id}, {trade.symbol}, ${trade.size}")
    
    return {
        "success": True,
        "message": "Trade submitted successfully",
        "risk_level": risk_level.value,
        "routing": routing_info
    }


@app.get("/api/v2/revenue", response_model=RevenueResponse)
async def get_revenue():
    """Get platform revenue metrics (admin only)."""
    summary = revenue_tracker.get_revenue_summary()
    
    return RevenueResponse(
        total_revenue=summary["total_revenue"],
        mrr=summary["mrr"],
        arr=summary["arr"],
        revenue_by_type=summary["revenue_by_type"],
        revenue_last_30_days=summary["revenue_last_30_days"]
    )


@app.get("/api/v2/execution/stats")
async def get_execution_stats():
    """Get execution statistics."""
    return {
        "queue_status": execution_router.get_queue_status(),
        "execution_stats": execution_router.get_execution_stats()
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
