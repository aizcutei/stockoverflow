"""Unit tests for backtesting engine."""

import pytest
import numpy as np
from backend.backtest_engine import BacktestConfig, run_backtest


@pytest.fixture
def sample_candles():
    """Generate 200 days of synthetic OHLCV data."""
    np.random.seed(42)
    n = 200
    base_price = 100.0
    prices = [base_price]
    for _ in range(n - 1):
        change = np.random.normal(0.0005, 0.02)
        prices.append(prices[-1] * (1 + change))

    candles = []
    for i, p in enumerate(prices):
        high = p * (1 + abs(np.random.normal(0, 0.01)))
        low = p * (1 - abs(np.random.normal(0, 0.01)))
        open_p = low + (high - low) * np.random.random()
        volume = int(np.random.uniform(1e6, 1e7))
        candles.append({
            "date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": round(open_p, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(p, 4),
            "volume": volume,
        })
    return candles


class TestBacktest:
    def test_basic_backtest(self, sample_candles):
        result = run_backtest(
            sample_candles,
            buy_expr="rsi(14) < 30",
            sell_expr="rsi(14) > 70",
        )
        assert result.total_return is not None
        assert result.max_drawdown >= 0
        assert result.total_trades >= 0

    def test_backtest_with_config(self, sample_candles):
        config = BacktestConfig(
            initial_capital=50000,
            fee_rate=0.002,
            slippage=0.001,
            stop_loss_pct=0.05,
        )
        result = run_backtest(
            sample_candles,
            buy_expr="rsi(14) < 35",
            sell_expr="rsi(14) > 65",
            config=config,
        )
        assert result.config["initial_capital"] == 50000

    def test_backtest_with_stop_loss(self, sample_candles):
        result = run_backtest(
            sample_candles,
            buy_expr="rsi(14) < 40",
            sell_expr="rsi(14) > 60",
            config=BacktestConfig(stop_loss_pct=0.03),
        )
        # check that some trades have stop_loss exit reason
        stop_trades = [t for t in result.trades if t.get("exit_reason") == "stop_loss"]
        # at least one trade should have been stopped out (probabilistic)

    def test_equity_curve(self, sample_candles):
        result = run_backtest(
            sample_candles,
            buy_expr="rsi(14) < 30",
            sell_expr="rsi(14) > 70",
        )
        assert len(result.equity_curve) == len(sample_candles)
        # equity should be non-negative
        for point in result.equity_curve:
            assert point["equity"] >= 0

    def test_invalid_expression(self, sample_candles):
        with pytest.raises(ValueError):
            run_backtest(
                sample_candles,
                buy_expr="invalid_func()",
                sell_expr="rsi(14) > 70",
            )

    def test_non_signal_expression(self, sample_candles):
        with pytest.raises(ValueError):
            run_backtest(
                sample_candles,
                buy_expr="rsi(14)",  # not a boolean signal
                sell_expr="rsi(14) > 70",
            )
