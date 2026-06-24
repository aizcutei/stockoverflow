"""Edge case tests for robustness."""

import pytest
from backend.indicators import calc_all_indicators, calc_overall_signal, calc_rsi, calc_macd
from backend.factor_engine import evaluate_expression, BUILTIN_FACTORS
from backend.backtest_engine import BacktestConfig, run_backtest


class TestEdgeCases:
    """Test boundary conditions and edge cases."""

    def test_minimum_candles(self):
        """RSI with exactly 15 candles (minimum for 14-period RSI)."""
        candles = [
            {"date": f"2025-01-{i+1:02d}", "open": 100, "high": 101, "low": 99, "close": 100 + i * 0.5, "volume": 1000000}
            for i in range(15)
        ]
        result = calc_rsi(candles)
        assert "signal" in result
        assert result["values"]["rsi"] is not None

    def test_flat_prices(self):
        """All same prices — should not crash."""
        from datetime import date, timedelta
        candles = [
            {"date": str(date(2025, 1, 1) + timedelta(days=i)), "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000000}
            for i in range(50)
        ]
        results = calc_all_indicators(candles)
        assert len(results) == 15
        for r in results:
            assert "signal" in r

    def test_very_volatile_prices(self):
        """Extreme price swings — should not crash."""
        import random
        from datetime import date, timedelta
        random.seed(42)
        candles = [
            {"date": str(date(2025, 1, 1) + timedelta(days=i)), "open": 100, "high": 100 * (1 + random.uniform(0, 0.2)),
             "low": 100 * (1 - random.uniform(0, 0.2)), "close": 100 * (1 + random.uniform(-0.1, 0.1)),
             "volume": 1000000}
            for i in range(100)
        ]
        results = calc_all_indicators(candles)
        assert len(results) == 15

    def test_single_candle_factor(self):
        """Factor eval with very few candles."""
        candles = [
            {"date": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000000},
        ]
        result = evaluate_expression("close", candles)
        # should either work or return an error, not crash
        assert "error" in result or "values" in result

    def test_backtest_no_trades(self):
        """Strategy that never triggers — should return zero trades."""
        from datetime import date, timedelta
        candles = [
            {"date": str(date(2025, 1, 1) + timedelta(days=i)), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000000}
            for i in range(50)
        ]
        result = run_backtest(candles, "rsi(14) < 5", "rsi(14) > 95")
        assert result.total_trades == 0
        assert result.total_return == 0

    def test_overall_signal_empty(self):
        """Overall signal with empty indicators."""
        result = calc_overall_signal([])
        assert result["signal"] == "NEUTRAL"

    def test_builtin_factors_valid(self):
        """All built-in factors should have valid expressions."""
        candles = [
            {"date": f"2025-{(i//28)+1:02d}-{(i%28)+1:02d}", "open": 100, "high": 101, "low": 99,
             "close": 100 + i * 0.1, "volume": 1000000}
            for i in range(200)
        ]
        for factor in BUILTIN_FACTORS:
            result = evaluate_expression(factor["expression"], candles)
            assert "error" not in result, f"Factor '{factor['name']}' failed: {result.get('error')}"

    def test_division_by_zero_protection(self):
        """Expressions that could cause division by zero."""
        from datetime import date, timedelta
        candles = [
            {"date": str(date(2025, 1, 1) + timedelta(days=i)), "open": 0.001, "high": 0.001, "low": 0.001, "close": 0.001, "volume": 1}
            for i in range(30)
        ]
        # should not crash
        result = evaluate_expression("rsi(14)", candles)
        assert result is not None

    def test_large_dataset(self):
        """Performance test with 2000 candles."""
        from datetime import date, timedelta
        candles = [
            {"date": str(date(2015, 1, 1) + timedelta(days=i)), "open": 100, "high": 101, "low": 99,
             "close": 100 + (i % 50) * 0.5, "volume": 1000000}
            for i in range(2000)
        ]
        results = calc_all_indicators(candles)
        assert len(results) == 15
