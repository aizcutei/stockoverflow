"""Unit tests for technical indicator calculations."""

import pytest
import numpy as np
from backend.indicators import (
    calc_macd,
    calc_bollinger,
    calc_ichimoku,
    calc_demark,
    calc_rsi,
    calc_stochastic,
    calc_adx,
    calc_vwap,
    calc_atr,
    calc_obv,
    calc_cci,
    calc_williams_r,
    calc_parabolic_sar,
    calc_mfi,
    calc_fibonacci,
    calc_all_indicators,
    calc_overall_signal,
)


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
            "date": f"2025-01-{(i % 28) + 1:02d}" if i < 28 else f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": round(open_p, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(p, 4),
            "volume": volume,
        })
    return candles


class TestMACD:
    def test_returns_correct_keys(self, sample_candles):
        result = calc_macd(sample_candles)
        assert "name" in result
        assert result["name"] == "MACD"
        assert "signal" in result
        assert "values" in result
        assert "series" in result

    def test_signal_is_valid(self, sample_candles):
        result = calc_macd(sample_candles)
        assert result["signal"] in ("BUY", "SELL", "NEUTRAL")

    def test_series_has_correct_length(self, sample_candles):
        result = calc_macd(sample_candles)
        assert len(result["series"]["macd"]) == len(sample_candles)
        assert len(result["series"]["signal"]) == len(sample_candles)
        assert len(result["series"]["histogram"]) == len(sample_candles)


class TestBollinger:
    def test_returns_correct_structure(self, sample_candles):
        result = calc_bollinger(sample_candles)
        assert result["name"] == "Bollinger Bands"
        assert "upper" in result["series"]
        assert "middle" in result["series"]
        assert "lower" in result["series"]

    def test_bands_order(self, sample_candles):
        result = calc_bollinger(sample_candles)
        vals = result["values"]
        if vals["upper"] and vals["lower"]:
            assert vals["upper"] > vals["lower"]


class TestRSI:
    def test_rsi_range(self, sample_candles):
        result = calc_rsi(sample_candles)
        rsi_val = result["values"]["rsi"]
        if rsi_val is not None:
            assert 0 <= rsi_val <= 100

    def test_signal_logic(self, sample_candles):
        result = calc_rsi(sample_candles)
        rsi_val = result["values"]["rsi"]
        if rsi_val is not None:
            if rsi_val < 30:
                assert result["signal"] == "BUY"
            elif rsi_val > 70:
                assert result["signal"] == "SELL"


class TestStochastic:
    def test_returns_k_and_d(self, sample_candles):
        result = calc_stochastic(sample_candles)
        assert "k" in result["values"]
        assert "d" in result["values"]

    def test_k_range(self, sample_candles):
        result = calc_stochastic(sample_candles)
        k = result["values"]["k"]
        if k is not None:
            assert 0 <= k <= 100


class TestADX:
    def test_returns_adx_value(self, sample_candles):
        result = calc_adx(sample_candles)
        assert "adx" in result["values"]
        assert "plus_di" in result["values"]
        assert "minus_di" in result["values"]


class TestATR:
    def test_atr_positive(self, sample_candles):
        result = calc_atr(sample_candles)
        atr_val = result["values"]["atr"]
        if atr_val is not None:
            assert atr_val > 0


class TestOBV:
    def test_obv_series(self, sample_candles):
        result = calc_obv(sample_candles)
        assert len(result["series"]["obv"]) == len(sample_candles)


class TestCCI:
    def test_cci_signal(self, sample_candles):
        result = calc_cci(sample_candles)
        assert result["signal"] in ("BUY", "SELL", "NEUTRAL")


class TestWilliamsR:
    def test_williams_range(self, sample_candles):
        result = calc_williams_r(sample_candles)
        wr = result["values"]["williams_r"]
        if wr is not None:
            assert -100 <= wr <= 0


class TestParabolicSAR:
    def test_sar_returns_trend(self, sample_candles):
        result = calc_parabolic_sar(sample_candles)
        assert result["values"]["trend"] in ("up", "down")


class TestMFI:
    def test_mfi_range(self, sample_candles):
        result = calc_mfi(sample_candles)
        mfi_val = result["values"]["mfi"]
        if mfi_val is not None:
            assert 0 <= mfi_val <= 100


class TestFibonacci:
    def test_fib_levels(self, sample_candles):
        result = calc_fibonacci(sample_candles)
        assert "fib_levels" in result
        fibs = result["fib_levels"]
        assert fibs["0.0"] < fibs["0.618"] < fibs["1.0"]


class TestAllIndicators:
    def test_returns_all_indicators(self, sample_candles):
        results = calc_all_indicators(sample_candles)
        names = [r["name"] for r in results]
        assert "MACD" in names
        assert "RSI" in names
        assert "Bollinger Bands" in names
        assert len(results) == 15


class TestOverallSignal:
    def test_overall_signal(self, sample_candles):
        indicators = calc_all_indicators(sample_candles)
        overall = calc_overall_signal(indicators)
        assert "signal" in overall
        assert "score" in overall
        assert "confidence" in overall
        assert overall["signal"] in ("BUY", "SELL", "NEUTRAL")
