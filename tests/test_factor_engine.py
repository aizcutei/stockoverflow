"""Unit tests for factor expression engine."""

import pytest
import numpy as np
from backend.factor_engine import evaluate_expression, BUILTIN_FACTORS


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


class TestFactorEvaluation:
    def test_simple_comparison(self, sample_candles):
        result = evaluate_expression("rsi(14) < 30", sample_candles)
        assert result["type"] == "signal"
        assert isinstance(result["latest_value"], bool)

    def test_numeric_factor(self, sample_candles):
        result = evaluate_expression("rsi(14)", sample_candles)
        assert result["type"] == "factor"
        assert len(result["values"]) == len(sample_candles)

    def test_complex_expression(self, sample_candles):
        result = evaluate_expression("rsi(14) < 50 and volume > sma(volume, 20)", sample_candles)
        assert result["type"] == "signal"

    def test_or_expression(self, sample_candles):
        result = evaluate_expression("rsi(14) < 30 or stochastic_k(14) < 20", sample_candles)
        assert result["type"] == "signal"

    def test_invalid_expression(self, sample_candles):
        result = evaluate_expression("invalid_function()", sample_candles)
        assert "error" in result

    def test_builtin_functions(self, sample_candles):
        for func_name in ["sma(volume, 20)", "ema(close, 12)", "atr(14)", "cci(20)"]:
            result = evaluate_expression(func_name, sample_candles)
            assert "error" not in result, f"Failed for {func_name}"


class TestBuiltinFactors:
    def test_library_has_factors(self):
        assert len(BUILTIN_FACTORS) > 0

    def test_factors_have_required_fields(self):
        for factor in BUILTIN_FACTORS:
            assert "name" in factor
            assert "expression" in factor
            assert "description" in factor

    def test_factors_evaluate(self, sample_candles):
        for factor in BUILTIN_FACTORS[:5]:  # test first 5
            result = evaluate_expression(factor["expression"], sample_candles)
            assert "error" not in result, f"Failed for {factor['name']}: {result.get('error')}"
