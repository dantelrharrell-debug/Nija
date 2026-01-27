# Execution Routing Model Architecture

## Executive Summary

The Execution Routing Model is the intelligent trade routing and isolation system that ensures each user's trades are executed independently, securely, and efficiently across multiple cryptocurrency exchanges. This system handles trade routing, user isolation, load balancing, and failover while maintaining the highest standards of security and performance.

## Design Goals

1. **User Isolation**: Complete separation between user accounts
2. **Fair Execution**: No user's trades can affect another user's execution
3. **Low Latency**: Sub-second trade routing and execution
4. **High Throughput**: Handle 1000+ trades per minute
5. **Reliability**: 99.9% trade execution success rate
6. **Exchange Diversity**: Support for 5+ cryptocurrency exchanges
7. **Intelligent Routing**: Route trades to best exchange based on liquidity, fees, and latency

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  Trading Strategy Layer                      │
│  APEX V7.1 Strategy / TradingView Webhooks                  │
└───────────────────────┬─────────────────────────────────────┘
                        │ Trade Signal
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                 Execution Router (Core)                      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Signal     │  │   Route      │  │   Execute    │     │
│  │ Validation   │→ │ Selection    │→ │   Manager    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   User       │  │  Position    │  │   Risk       │     │
│  │ Permissions  │  │   Manager    │  │   Manager    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└───────────────────────┬─────────────────────────────────────┘
                        │
         ┌──────────────┼──────────────┬──────────────┐
         │              │              │              │
         ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐
│  Coinbase    │ │  Kraken  │ │   Binance  │ │   Alpaca     │
│  Executor    │ │ Executor │ │  Executor  │ │   Executor   │
│              │ │          │ │            │ │              │
│ - Queue      │ │ - Queue  │ │ - Queue    │ │ - Queue      │
│ - Rate Limit │ │ - Rate   │ │ - Rate     │ │ - Rate       │
│ - Circuit    │ │   Limit  │ │   Limit    │ │   Limit      │
│   Breaker    │ │ - Circuit│ │ - Circuit  │ │ - Circuit    │
│ - Retry      │ │   Breaker│ │   Breaker  │ │   Breaker    │
└──────┬───────┘ └────┬─────┘ └──────┬─────┘ └──────┬───────┘
       │              │              │              │
       └──────────────┴──────────────┴──────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                  Result Aggregator                           │
│  - Collect execution results                                 │
│  - Update position state                                     │
│  - Notify users                                              │
│  - Log to database                                           │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Execution Router Core

The brain of the execution system that orchestrates all trade routing decisions.

**Implementation:**

```python
# execution_router.py
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """Execution status states."""
    PENDING = "pending"
    ROUTING = "routing"
    QUEUED = "queued"
    EXECUTING = "executing"
    FILLED = "filled"
    PARTIAL_FILL = "partial_fill"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TradeSignal:
    """
    Standardized trade signal from strategy layer.
    """
    user_id: str
    pair: str
    side: str  # 'buy' or 'sell'
    size_usd: float
    signal_type: str  # 'entry', 'exit', 'profit_take', 'stop_loss'
    strategy: str  # 'apex_v71', 'tradingview', etc.
    timestamp: datetime
    metadata: Dict = None


@dataclass
class RouteDecision:
    """
    Routing decision for a trade signal.
    """
    signal: TradeSignal
    broker: str  # Selected exchange
    execution_method: str  # 'market', 'limit', 'twap'
    priority: int  # 1 (highest) to 5 (lowest)
    estimated_fees: float
    estimated_latency_ms: float
    reason: str  # Why this route was chosen


class ExecutionRouter:
    """
    Core execution routing engine.
    Decides which exchange to route each trade to.
    """
    
    def __init__(self):
        self.executors = {}  # broker_name -> BrokerExecutor
        self.active_routes = {}  # signal_id -> RouteDecision
        self.performance_tracker = PerformanceTracker()
        logger.info("Execution router initialized")
    
    def register_executor(self, broker_name: str, executor):
        """Register a broker executor."""
        self.executors[broker_name] = executor
        logger.info(f"Registered executor for {broker_name}")
    
    async def route_signal(self, signal: TradeSignal) -> RouteDecision:
        """
        Route a trade signal to the best exchange.
        
        Routing Factors (in priority order):
        1. User permissions (which exchanges user can trade on)
        2. Pair availability (is pair listed on exchange?)
        3. Liquidity (sufficient liquidity for size?)
        4. Fees (lowest fee structure)
        5. Historical performance (success rate, latency)
        6. Current load (least busy executor)
        """
        logger.info(f"Routing signal for user {signal.user_id}: {signal.side} {signal.size_usd} {signal.pair}")
        
        # Step 1: Get user permissions
        from execution import get_permission_validator
        validator = get_permission_validator()
        permissions = validator.get_user_permissions(signal.user_id)
        
        if not permissions:
            raise ValueError(f"User {signal.user_id} not found")
        
        if not permissions.enabled:
            raise ValueError(f"Trading disabled for user {signal.user_id}")
        
        # Step 2: Validate trade
        is_valid, error = validator.validate_trade(
            signal.user_id,
            signal.pair,
            signal.size_usd
        )
        
        if not is_valid:
            raise ValueError(f"Trade validation failed: {error}")
        
        # Step 3: Get available brokers for user
        from auth import get_api_key_manager
        api_manager = get_api_key_manager()
        user_brokers = api_manager.list_user_brokers(signal.user_id)
        
        if not user_brokers:
            raise ValueError(f"No brokers configured for user {signal.user_id}")
        
        # Step 4: Score each broker
        broker_scores = []
        for broker in user_brokers:
            if broker not in self.executors:
                continue
            
            score = await self._score_broker(
                broker=broker,
                signal=signal,
                executor=self.executors[broker]
            )
            
            if score:
                broker_scores.append(score)
        
        if not broker_scores:
            raise ValueError(f"No suitable brokers found for pair {signal.pair}")
        
        # Step 5: Select best broker (highest score)
        broker_scores.sort(key=lambda x: x['total_score'], reverse=True)
        best_broker = broker_scores[0]
        
        # Step 6: Create routing decision
        decision = RouteDecision(
            signal=signal,
            broker=best_broker['broker'],
            execution_method=best_broker['execution_method'],
            priority=best_broker['priority'],
            estimated_fees=best_broker['estimated_fees'],
            estimated_latency_ms=best_broker['estimated_latency_ms'],
            reason=best_broker['reason']
        )
        
        logger.info(f"Routed to {decision.broker}: {decision.reason}")
        
        return decision
    
    async def _score_broker(
        self,
        broker: str,
        signal: TradeSignal,
        executor
    ) -> Optional[Dict]:
        """
        Score a broker for this trade signal.
        
        Returns scoring dict or None if broker unsuitable.
        """
        # Check if pair is available on this broker
        if not await executor.has_pair(signal.pair):
            logger.debug(f"{broker}: Pair {signal.pair} not available")
            return None
        
        # Get broker info
        info = await executor.get_info()
        
        # Check if broker is healthy
        if not info['healthy']:
            logger.debug(f"{broker}: Not healthy (circuit breaker open)")
            return None
        
        # Check if broker has sufficient liquidity
        liquidity = await executor.get_liquidity(signal.pair)
        if liquidity < signal.size_usd * 2:  # Need 2x liquidity
            logger.debug(f"{broker}: Insufficient liquidity (${liquidity:.2f} < ${signal.size_usd * 2:.2f})")
            return None
        
        # Calculate scores (0-100 each)
        
        # 1. Fee score (lower fees = higher score)
        fee_pct = info['fee_structure']['maker']  # Use maker fee
        fee_score = max(0, 100 - (fee_pct * 10000))  # 0.5% fee = 50 score
        
        # 2. Latency score (lower latency = higher score)
        avg_latency_ms = info['avg_latency_ms']
        latency_score = max(0, 100 - (avg_latency_ms / 10))  # 500ms = 50 score
        
        # 3. Success rate score
        success_rate = info['success_rate']
        success_score = success_rate * 100  # 95% success = 95 score
        
        # 4. Load score (less busy = higher score)
        queue_depth = info['queue_depth']
        max_queue = 100
        load_score = max(0, 100 - (queue_depth / max_queue * 100))
        
        # 5. Historical performance score for this pair
        pair_performance = self.performance_tracker.get_pair_performance(broker, signal.pair)
        pair_score = pair_performance['success_rate'] * 100 if pair_performance else 50
        
        # Weighted total score
        total_score = (
            fee_score * 0.30 +        # 30% weight on fees
            latency_score * 0.20 +    # 20% weight on latency
            success_score * 0.25 +    # 25% weight on reliability
            load_score * 0.15 +       # 15% weight on current load
            pair_score * 0.10         # 10% weight on pair-specific performance
        )
        
        # Determine execution method
        if signal.size_usd > 10000:
            execution_method = 'twap'  # Time-weighted average price for large orders
        elif signal.signal_type in ['stop_loss', 'exit']:
            execution_method = 'market'  # Quick exit
        else:
            execution_method = 'limit'  # Best price for entries
        
        # Determine priority
        if signal.signal_type == 'stop_loss':
            priority = 1  # Highest priority
        elif signal.signal_type == 'exit':
            priority = 2
        elif signal.signal_type == 'entry':
            priority = 3
        else:
            priority = 4
        
        # Estimate fees
        estimated_fees = signal.size_usd * fee_pct
        
        return {
            'broker': broker,
            'total_score': total_score,
            'fee_score': fee_score,
            'latency_score': latency_score,
            'success_score': success_score,
            'load_score': load_score,
            'pair_score': pair_score,
            'execution_method': execution_method,
            'priority': priority,
            'estimated_fees': estimated_fees,
            'estimated_latency_ms': avg_latency_ms,
            'reason': f"Score: {total_score:.1f} (fees: {fee_score:.0f}, latency: {latency_score:.0f}, success: {success_score:.0f})"
        }
    
    async def execute_route(self, decision: RouteDecision) -> Dict:
        """
        Execute a routing decision.
        
        Returns execution result.
        """
        executor = self.executors[decision.broker]
        
        # Execute trade
        result = await executor.execute_trade(
            user_id=decision.signal.user_id,
            pair=decision.signal.pair,
            side=decision.signal.side,
            size_usd=decision.signal.size_usd,
            order_type=decision.execution_method,
            priority=decision.priority
        )
        
        # Track performance
        self.performance_tracker.record_execution(
            broker=decision.broker,
            pair=decision.signal.pair,
            result=result
        )
        
        return result


class PerformanceTracker:
    """
    Tracks execution performance per broker and pair.
    """
    
    def __init__(self):
        self.executions = {}  # broker -> pair -> [results]
        self.window_size = 100  # Keep last 100 executions per pair
    
    def record_execution(self, broker: str, pair: str, result: Dict):
        """Record an execution result."""
        if broker not in self.executions:
            self.executions[broker] = {}
        
        if pair not in self.executions[broker]:
            self.executions[broker][pair] = []
        
        # Add result
        self.executions[broker][pair].append({
            'timestamp': datetime.now(),
            'success': result['status'] == 'filled',
            'latency_ms': result.get('latency_ms', 0),
            'slippage_pct': result.get('slippage_pct', 0)
        })
        
        # Keep only last N executions
        if len(self.executions[broker][pair]) > self.window_size:
            self.executions[broker][pair] = self.executions[broker][pair][-self.window_size:]
    
    def get_pair_performance(self, broker: str, pair: str) -> Optional[Dict]:
        """Get performance stats for broker + pair."""
        if broker not in self.executions or pair not in self.executions[broker]:
            return None
        
        results = self.executions[broker][pair]
        if not results:
            return None
        
        successes = sum(1 for r in results if r['success'])
        success_rate = successes / len(results)
        
        avg_latency = sum(r['latency_ms'] for r in results) / len(results)
        avg_slippage = sum(r['slippage_pct'] for r in results) / len(results)
        
        return {
            'success_rate': success_rate,
            'avg_latency_ms': avg_latency,
            'avg_slippage_pct': avg_slippage,
            'sample_size': len(results)
        }
```

### 2. Broker Executor

Each exchange has its own executor that handles queue management, rate limiting, and execution.

**Implementation:**

```python
# broker_executor.py
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRequest:
    """Request to execute a trade."""
    request_id: str
    user_id: str
    pair: str
    side: str
    size_usd: float
    order_type: str  # 'market', 'limit', 'twap'
    priority: int
    timestamp: datetime
    callback: Optional[callable] = None


class CircuitBreaker:
    """
    Circuit breaker for broker health management.
    
    States:
    - CLOSED: Normal operation
    - OPEN: Too many failures, reject all requests
    - HALF_OPEN: Testing if broker recovered
    """
    
    def __init__(self, failure_threshold=5, timeout_seconds=60):
        self.failure_threshold = failure_threshold
        self.timeout = timedelta(seconds=timeout_seconds)
        self.failures = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
    
    def record_success(self):
        """Record successful execution."""
        if self.state == 'HALF_OPEN':
            # Recovery confirmed, close circuit
            self.state = 'CLOSED'
            self.failures = 0
            logger.info("Circuit breaker: HALF_OPEN -> CLOSED (recovered)")
    
    def record_failure(self):
        """Record failed execution."""
        self.failures += 1
        self.last_failure_time = datetime.now()
        
        if self.failures >= self.failure_threshold:
            self.state = 'OPEN'
            logger.warning(f"Circuit breaker: CLOSED -> OPEN ({self.failures} failures)")
    
    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        if self.state == 'CLOSED':
            return True
        
        if self.state == 'OPEN':
            # Check if timeout elapsed
            if datetime.now() - self.last_failure_time > self.timeout:
                self.state = 'HALF_OPEN'
                logger.info("Circuit breaker: OPEN -> HALF_OPEN (testing recovery)")
                return True
            return False
        
        # HALF_OPEN state
        return True


class RateLimiter:
    """
    Token bucket rate limiter.
    """
    
    def __init__(self, rate_per_second: int, burst_size: int = None):
        self.rate = rate_per_second
        self.burst_size = burst_size or rate_per_second * 2
        self.tokens = self.burst_size
        self.last_update = datetime.now()
    
    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = datetime.now()
        elapsed = (now - self.last_update).total_seconds()
        
        # Add tokens based on rate
        new_tokens = elapsed * self.rate
        self.tokens = min(self.burst_size, self.tokens + new_tokens)
        self.last_update = now
    
    async def acquire(self, tokens: int = 1) -> bool:
        """
        Acquire tokens (wait if necessary).
        
        Returns True when tokens acquired.
        """
        while True:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            # Wait for tokens to refill
            wait_time = (tokens - self.tokens) / self.rate
            await asyncio.sleep(wait_time)
    
    def try_acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens without waiting.
        
        Returns True if tokens acquired, False otherwise.
        """
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        
        return False


class BrokerExecutor:
    """
    Executor for a specific broker/exchange.
    
    Features:
    - Priority queue for trade requests
    - Rate limiting per exchange API limits
    - Circuit breaker for fault tolerance
    - Retry logic with exponential backoff
    - Performance tracking
    """
    
    def __init__(
        self,
        broker_name: str,
        rate_limit: int = 10,  # requests per second
        max_queue_size: int = 1000
    ):
        self.broker_name = broker_name
        self.queue = []  # Priority queue: [(priority, timestamp, request)]
        self.max_queue_size = max_queue_size
        self.rate_limiter = RateLimiter(rate_per_second=rate_limit)
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout_seconds=60)
        self.active_executions = 0
        self.total_executions = 0
        self.successful_executions = 0
        self.worker_task = None
        self.running = False
        
        logger.info(f"Broker executor initialized for {broker_name} (rate: {rate_limit}/s)")
    
    async def start(self):
        """Start the executor worker."""
        if self.running:
            return
        
        self.running = True
        self.worker_task = asyncio.create_task(self._worker())
        logger.info(f"{self.broker_name} executor started")
    
    async def stop(self):
        """Stop the executor worker."""
        self.running = False
        if self.worker_task:
            await self.worker_task
        logger.info(f"{self.broker_name} executor stopped")
    
    async def execute_trade(
        self,
        user_id: str,
        pair: str,
        side: str,
        size_usd: float,
        order_type: str = 'market',
        priority: int = 3
    ) -> Dict:
        """
        Queue a trade for execution.
        
        Returns a future that resolves when trade completes.
        """
        # Check circuit breaker
        if not self.circuit_breaker.can_execute():
            raise Exception(f"{self.broker_name} circuit breaker is OPEN")
        
        # Check queue size
        if len(self.queue) >= self.max_queue_size:
            raise Exception(f"{self.broker_name} queue is full ({self.max_queue_size})")
        
        # Create execution request
        request_id = f"{user_id}_{pair}_{int(datetime.now().timestamp())}"
        future = asyncio.Future()
        
        request = ExecutionRequest(
            request_id=request_id,
            user_id=user_id,
            pair=pair,
            side=side,
            size_usd=size_usd,
            order_type=order_type,
            priority=priority,
            timestamp=datetime.now(),
            callback=lambda result: future.set_result(result)
        )
        
        # Add to priority queue
        # Lower priority number = higher priority
        # Secondary sort by timestamp (FIFO within same priority)
        self.queue.append((priority, request.timestamp, request))
        self.queue.sort(key=lambda x: (x[0], x[1]))
        
        logger.info(f"Queued trade: {request_id} (priority {priority}, queue depth: {len(self.queue)})")
        
        # Wait for execution result
        return await future
    
    async def _worker(self):
        """
        Background worker that processes queued trades.
        """
        logger.info(f"{self.broker_name} worker started")
        
        while self.running:
            # Check if queue has requests
            if not self.queue:
                await asyncio.sleep(0.1)
                continue
            
            # Check circuit breaker
            if not self.circuit_breaker.can_execute():
                await asyncio.sleep(1)
                continue
            
            # Get next request (highest priority)
            priority, timestamp, request = self.queue.pop(0)
            
            # Acquire rate limit token
            await self.rate_limiter.acquire()
            
            # Execute trade
            self.active_executions += 1
            self.total_executions += 1
            
            try:
                result = await self._execute_trade(request)
                
                # Record success
                self.successful_executions += 1
                self.circuit_breaker.record_success()
                
                # Callback with result
                if request.callback:
                    request.callback(result)
            
            except Exception as e:
                logger.error(f"Trade execution failed: {e}")
                
                # Record failure
                self.circuit_breaker.record_failure()
                
                # Callback with error
                if request.callback:
                    request.callback({
                        'status': 'failed',
                        'error': str(e)
                    })
            
            finally:
                self.active_executions -= 1
        
        logger.info(f"{self.broker_name} worker stopped")
    
    async def _execute_trade(self, request: ExecutionRequest) -> Dict:
        """
        Actually execute the trade on the broker.
        
        This calls the broker-specific adapter.
        """
        # Get user credentials
        from auth import get_api_key_manager
        api_manager = get_api_key_manager()
        
        creds = api_manager.get_user_api_key(request.user_id, self.broker_name)
        if not creds:
            raise ValueError(f"No credentials for user {request.user_id} on {self.broker_name}")
        
        # Get broker adapter
        from execution.broker_adapter import SecureBrokerAdapter
        adapter = SecureBrokerAdapter(
            user_id=request.user_id,
            broker_name=self.broker_name
        )
        
        # Execute trade
        start_time = datetime.now()
        
        result = await adapter.place_order_async(
            pair=request.pair,
            side=request.side,
            size_usd=request.size_usd,
            order_type=request.order_type
        )
        
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        result['latency_ms'] = latency_ms
        
        logger.info(f"Trade executed: {request.request_id} in {latency_ms:.0f}ms")
        
        return result
    
    async def get_info(self) -> Dict:
        """Get executor info for routing decisions."""
        success_rate = (
            self.successful_executions / self.total_executions
            if self.total_executions > 0
            else 1.0
        )
        
        return {
            'broker': self.broker_name,
            'healthy': self.circuit_breaker.state != 'OPEN',
            'circuit_state': self.circuit_breaker.state,
            'queue_depth': len(self.queue),
            'active_executions': self.active_executions,
            'total_executions': self.total_executions,
            'success_rate': success_rate,
            'avg_latency_ms': 100,  # TODO: Track actual latency
            'fee_structure': {
                'maker': 0.004,  # 0.4% (example)
                'taker': 0.006   # 0.6% (example)
            }
        }
    
    async def has_pair(self, pair: str) -> bool:
        """Check if broker supports this trading pair."""
        # TODO: Query broker for pair availability
        return True
    
    async def get_liquidity(self, pair: str) -> float:
        """Get current liquidity for pair on this broker."""
        # TODO: Query broker for order book depth
        return 100000.0  # Example: $100k liquidity
```

### 3. User Isolation

Each user's trades are completely isolated from other users.

**Key Isolation Mechanisms:**

1. **Separate API Credentials**: Each user uses their own exchange API keys
2. **Independent Queues**: Trades from different users don't interfere
3. **Per-User Rate Limiting**: One user can't exhaust rate limits for others
4. **Isolated Position Tracking**: Each user's positions tracked separately
5. **Separate Risk Management**: Each user has their own risk limits

**Implementation:**

```python
# user_isolation.py

class IsolatedUserContext:
    """
    Execution context for a single user.
    Ensures complete isolation from other users.
    """
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.active_trades = {}  # trade_id -> trade_info
        self.position_manager = UserPositionManager(user_id)
        self.risk_manager = UserRiskManager(user_id)
        self.rate_limiter = RateLimiter(rate_per_second=1)  # Per-user limit
    
    async def can_trade(self, signal: TradeSignal) -> Tuple[bool, Optional[str]]:
        """
        Check if user can execute this trade.
        
        Checks:
        1. User permissions
        2. Risk limits
        3. Position limits
        4. Per-user rate limits
        """
        # Check hard controls
        from controls import get_hard_controls
        controls = get_hard_controls()
        
        can_trade, error = controls.can_trade(self.user_id)
        if not can_trade:
            return False, error
        
        # Check risk limits
        can_risk, error = self.risk_manager.can_take_position(
            pair=signal.pair,
            size_usd=signal.size_usd
        )
        if not can_risk:
            return False, error
        
        # Check position limits
        can_position, error = self.position_manager.can_add_position(
            pair=signal.pair
        )
        if not can_position:
            return False, error
        
        # Check per-user rate limit
        if not self.rate_limiter.try_acquire():
            return False, "User rate limit exceeded (max 1 trade/sec)"
        
        return True, None
```

### 4. Load Balancing

Distribute trades across executors to prevent overload.

**Strategies:**

1. **Round Robin**: Simple rotation between executors
2. **Least Loaded**: Route to executor with smallest queue
3. **Weighted**: Route based on executor performance
4. **Adaptive**: Adjust weights based on recent performance

### 5. Failover & Retry

Handle failures gracefully with automatic retry and fallback.

**Retry Policy:**

```python
# retry_policy.py

class RetryPolicy:
    """
    Exponential backoff retry policy.
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    async def execute_with_retry(self, func, *args, **kwargs):
        """
        Execute function with exponential backoff retry.
        """
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            
            except Exception as e:
                if attempt == self.max_retries:
                    # Final attempt failed
                    raise
                
                # Calculate delay
                delay = min(
                    self.max_delay,
                    self.base_delay * (2 ** attempt)
                )
                
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
```

## Integration with Existing NIJA Code

### Update execution/broker_adapter.py

Add async support and integration with new routing system:

```python
class SecureBrokerAdapter:
    """Enhanced broker adapter with async support."""
    
    async def place_order_async(
        self,
        pair: str,
        side: str,
        size_usd: float,
        order_type: str = 'market'
    ) -> Dict:
        """
        Place order asynchronously.
        Integrates with execution router.
        """
        # Create trade signal
        signal = TradeSignal(
            user_id=self.user_id,
            pair=pair,
            side=side,
            size_usd=size_usd,
            signal_type='entry',
            strategy='manual',
            timestamp=datetime.now()
        )
        
        # Get execution router
        from execution.routing import get_execution_router
        router = get_execution_router()
        
        # Route and execute
        decision = await router.route_signal(signal)
        result = await router.execute_route(decision)
        
        return result
```

## Performance Benchmarks

### Target Metrics
- **Routing Latency**: < 10ms p99
- **Execution Latency**: < 500ms p99 (market orders)
- **Throughput**: 1000+ trades/minute
- **Success Rate**: > 99%
- **Failover Time**: < 5 seconds

### Load Testing

```python
# load_test.py
import asyncio
import time

async def load_test():
    """Simulate 1000 concurrent users placing trades."""
    
    async def user_trade(user_id):
        signal = TradeSignal(
            user_id=f"user_{user_id}",
            pair="BTC-USD",
            side="buy",
            size_usd=100.0,
            signal_type="entry",
            strategy="test",
            timestamp=datetime.now()
        )
        
        router = get_execution_router()
        decision = await router.route_signal(signal)
        result = await router.execute_route(decision)
        return result
    
    # Generate 1000 concurrent trades
    start_time = time.time()
    tasks = [user_trade(i) for i in range(1000)]
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start_time
    
    # Analyze results
    successes = sum(1 for r in results if r['status'] == 'filled')
    success_rate = successes / len(results) * 100
    throughput = len(results) / elapsed
    
    print(f"Completed {len(results)} trades in {elapsed:.2f}s")
    print(f"Success rate: {success_rate:.1f}%")
    print(f"Throughput: {throughput:.0f} trades/sec")
```

## Monitoring & Observability

### Metrics to Track
- Routing decisions per second
- Execution latency (p50, p95, p99)
- Queue depths per executor
- Circuit breaker state changes
- Success/failure rates per broker
- Slippage per broker
- Fee costs per broker

### Dashboards

**Grafana Dashboard - Execution Router:**

```json
{
  "dashboard": {
    "title": "NIJA Execution Router",
    "panels": [
      {
        "title": "Trades Routed per Second",
        "targets": [
          {"expr": "rate(nija_trades_routed_total[1m])"}
        ]
      },
      {
        "title": "Routing Latency",
        "targets": [
          {"expr": "histogram_quantile(0.99, nija_routing_latency_seconds)"}
        ]
      },
      {
        "title": "Execution Success Rate by Broker",
        "targets": [
          {"expr": "rate(nija_executions_success_total[5m]) / rate(nija_executions_total[5m])"}
        ]
      },
      {
        "title": "Queue Depth by Broker",
        "targets": [
          {"expr": "nija_executor_queue_depth"}
        ]
      }
    ]
  }
}
```

## Deployment

### Kubernetes Deployment

```yaml
# execution-router-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: execution-router
spec:
  replicas: 3
  selector:
    matchLabels:
      app: execution-router
  template:
    metadata:
      labels:
        app: execution-router
    spec:
      containers:
      - name: router
        image: nija/execution-router:latest
        env:
        - name: VAULT_ADDR
          value: "https://vault.nija.io:8200"
        - name: POSTGRES_URL
          valueFrom:
            secretKeyRef:
              name: postgres-credentials
              key: url
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
```

## Security Considerations

### API Key Isolation
- Each user's API keys stored separately in Vault
- No shared credentials between users
- Credentials never logged or exposed

### Rate Limiting
- Per-user rate limits prevent abuse
- Global rate limits prevent system overload
- Exchange-specific rate limits honored

### Audit Logging
- All trade routing decisions logged
- All executions logged with user ID
- Failed trades logged with reason
- Immutable audit trail

## Cost Optimization

### Intelligent Fee Routing
```python
def calculate_total_cost(broker, size_usd):
    """Calculate total cost including fees."""
    fee_pct = BROKER_FEES[broker]
    fee_usd = size_usd * fee_pct
    
    # Consider withdrawal fees if relevant
    withdrawal_fee = WITHDRAWAL_FEES.get(broker, 0)
    
    return fee_usd + withdrawal_fee

# Route to cheapest broker
cheapest_broker = min(
    available_brokers,
    key=lambda b: calculate_total_cost(b, size_usd)
)
```

## Success Criteria

- ✅ 99.9% execution success rate
- ✅ < 500ms p99 execution latency
- ✅ Support 1000+ users concurrently
- ✅ Zero cross-user contamination
- ✅ Automatic failover working
- ✅ All trades auditable
- ✅ Cost savings from smart routing

## Related Documentation

- [Multi-User Platform Architecture](./MULTI_USER_PLATFORM_ARCHITECTURE.md)
- [Secure API Vault System](./SECURE_API_VAULT_ARCHITECTURE.md)
- [Mobile App UX Flow](./MOBILE_APP_UX_ARCHITECTURE.md)
- [Current Architecture](./ARCHITECTURE.md)

---

**Document Version**: 1.0  
**Last Updated**: January 27, 2026  
**Status**: ✅ Ready for Implementation  
**Owner**: Trading Team
