import unittest
import pandas as pd

from bot.control.strategy_detectors import BreakRetestDetector, DetectorContext
from bot.control.trading_context import TradingContext


def ctx():
    return DetectorContext(
        symbol="BTC-USD",
        broker="kraken",
        market_regime="trending",
        trading_context=TradingContext(
            user_id="u1", trading_account_id="a1", broker="kraken",
            broker_account_id="ka1", strategy_instance_id="break_retest",
            portfolio_id="p1", request_id="r1", correlation_id="c1",
            environment="paper", mode="paper", decision_id="d1",
        ),
    )


def frame(direction):
    rows=[]
    for i in range(40):
        rows.append({"open":100.0,"high":101.0,"low":99.0,"close":100.0,"volume":100.0})
    if direction=="long":
        rows[-2]={"open":100.5,"high":103.0,"low":100.4,"close":102.0,"volume":150.0}
        rows[-1]={"open":101.0,"high":102.2,"low":100.8,"close":101.7,"volume":120.0}
    else:
        rows[-2]={"open":99.5,"high":99.6,"low":97.0,"close":98.0,"volume":150.0}
        rows[-1]={"open":99.0,"high":99.2,"low":97.8,"close":98.3,"volume":120.0}
    return pd.DataFrame(rows)


class TestBreakRetestDetector(unittest.TestCase):
    def test_long_break_retest(self):
        signal=BreakRetestDetector().detect(frame("long"),ctx())
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction,"long")
        self.assertEqual(signal.strategy,"BREAK_RETEST")

    def test_short_break_retest(self):
        signal=BreakRetestDetector().detect(frame("short"),ctx())
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction,"short")

    def test_no_break_no_signal(self):
        df=frame("long")
        df.iloc[-2]=df.iloc[-3]
        self.assertIsNone(BreakRetestDetector().detect(df,ctx()))


if __name__=="__main__":
    unittest.main()
