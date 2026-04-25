print("[DEBUG] End of live_trading.py script reached. If you see this, the process exited the main function.")
# bot/live_bot_script/live_trading.py
print("=== NIJA DEBUG: CODE UPDATED 2025-12-11 [live_bot_script/live_trading.py] ===")
import logging
import time

try:
    from bot.execution_pipeline import get_execution_pipeline, PipelineRequest
except ImportError:
    try:
        from execution_pipeline import get_execution_pipeline, PipelineRequest
    except ImportError:
        get_execution_pipeline = None  # type: ignore
        PipelineRequest = None  # type: ignore

logger = logging.getLogger(__name__)


def _submit_startup_order(client, product_id: str, size_usd: float):
    if get_execution_pipeline is None or PipelineRequest is None:
        raise RuntimeError("ExecutionPipeline unavailable and direct broker bypass blocked")

    price_hint = None
    if hasattr(client, 'get_best_bid_ask'):
        try:
            ticker = client.get_best_bid_ask(product_ids=[product_id])
            pricebooks = (ticker or {}).get('pricebooks', [{}])
            book = pricebooks[0] if pricebooks else {}
            bid = float((book.get('bids') or [{}])[0].get('price', 0) or 0)
            ask = float((book.get('asks') or [{}])[0].get('price', 0) or 0)
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
            if mid > 0:
                price_hint = mid
        except Exception:
            price_hint = None

    result = get_execution_pipeline().execute(
        PipelineRequest(
            strategy='LiveTradingStartup',
            symbol=product_id,
            side='buy',
            size_usd=float(size_usd),
            order_type='MARKET',
            preferred_broker='coinbase',
            price_hint_usd=price_hint,
        )
    )
    if not result.success:
        raise RuntimeError(result.error or 'ExecutionPipeline rejected startup order')

    return {
        'status': 'filled',
        'order_id': 'pipeline',
        'filled_price': result.fill_price,
        'filled_size_usd': result.filled_size_usd,
        'broker': result.broker,
    }

def run_live_trading(client):
    """
    Run live trading loop safely.
    Places a minimal $1 order once on startup, then continues normal trading.
    """
    try:
        # 1️⃣ Check account balances
        accounts = client.get_accounts()
        usd_account = next((a for a in accounts if a['currency'] == 'USD'), None)

        if not usd_account:
            logger.error("No USD account found. Cannot place live orders.")
            return

        usd_balance = float(usd_account['balance']['amount'])
        logger.info(f"USD Balance: ${usd_balance:.2f}")

        # 2️⃣ Place minimal order ONCE
        minimal_order_amount = 1.00  # $1 trade
        if usd_balance >= minimal_order_amount:
            order = _submit_startup_order(
                client=client,
                product_id='BTC-USD',
                size_usd=minimal_order_amount,
            )
            logger.info(f"✅ First minimal live order placed: {order}")
        else:
            logger.warning(f"Insufficient balance for minimal order (${minimal_order_amount}).")

        # 3️⃣ Main live trading loop (now calls real trading logic)
        from trading_strategy import TradingStrategy
        strategy = TradingStrategy()
        run_cycle = getattr(strategy, 'run_trading_cycle', None)
        if run_cycle is None:
            raise AttributeError('TradingStrategy.run_trading_cycle is unavailable')
        logger.info("Starting main live trading loop...")
        while True:
            logger.debug(f"[DEBUG] Main loop iteration started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"[DEBUG] Main loop iteration started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            try:
                start = time.perf_counter()
                run_cycle()
                duration = time.perf_counter() - start
                logger.info(f"Scan cycle: {duration:.4f}s")
                logger.debug(f"[DEBUG] Main loop iteration finished at {time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"[DEBUG] Main loop iteration finished at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as e:
                logger.error(f"[ERROR] Exception in trading strategy: {e}")
                print(f"[ERROR] Exception in trading strategy: {e}")
            time.sleep(10)  # reduce interval for visibility

    except Exception as e:
        logger.error(f"Error in live trading: {e}")
        print(f"Error in live trading: {e}")
        import traceback
        logger.error(traceback.format_exc())
        print(traceback.format_exc())
    finally:
        logger.error("[DEBUG] run_live_trading() has exited unexpectedly!")
        print("[DEBUG] run_live_trading() has exited unexpectedly!")
