"""Factor expression engine — evaluate custom factor expressions on OHLCV data.

Supports expressions like:
  rsi(14) < 30
  macd_cross('bullish') and volume > sma(volume, 20)
  close > bb_upper(20, 2) and adx(14) > 25
  stochastic_k(14) < 20 or rsi(14) < 30
"""

from __future__ import annotations

import ast
import operator
import re

import numpy as np
import pandas as pd


def _build_df(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


# ── Built-in functions available in expressions ──────────────────────


class FactorFunctions:
    """Collection of functions available in factor expressions."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.close = df["close"]
        self.high = df["high"]
        self.low = df["low"]
        self.open = df["open"]
        self.volume = df["volume"]

    def sma(self, series: pd.Series, period: int) -> pd.Series:
        return series.rolling(period).mean()

    def ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def rsi(self, period: int = 14) -> pd.Series:
        delta = self.close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - 100 / (1 + rs)

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
        ema_fast = self.close.ewm(span=fast, adjust=False).mean()
        ema_slow = self.close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return {"macd": macd_line, "signal": signal_line, "histogram": hist}

    def macd_cross(self, direction: str = "bullish") -> pd.Series:
        m = self.macd()
        hist = m["histogram"]
        if direction == "bullish":
            return (hist > 0) & (hist.shift(1) <= 0)
        else:
            return (hist < 0) & (hist.shift(1) >= 0)

    def bb_upper(self, period: int = 20, std: float = 2.0) -> pd.Series:
        sma = self.close.rolling(period).mean()
        s = self.close.rolling(period).std()
        return sma + std * s

    def bb_lower(self, period: int = 20, std: float = 2.0) -> pd.Series:
        sma = self.close.rolling(period).mean()
        s = self.close.rolling(period).std()
        return sma - std * s

    def bb_middle(self, period: int = 20) -> pd.Series:
        return self.close.rolling(period).mean()

    def adx(self, period: int = 14) -> pd.Series:
        plus_dm = self.high.diff()
        minus_dm = -self.low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
        tr1 = self.high - self.low
        tr2 = (self.high - self.close.shift(1)).abs()
        tr3 = (self.low - self.close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        return dx.ewm(span=period, adjust=False).mean()

    def atr(self, period: int = 14) -> pd.Series:
        tr1 = self.high - self.low
        tr2 = (self.high - self.close.shift(1)).abs()
        tr3 = (self.low - self.close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    def stochastic_k(self, period: int = 14) -> pd.Series:
        lowest = self.low.rolling(period).min()
        highest = self.high.rolling(period).max()
        return 100 * (self.close - lowest) / (highest - lowest)

    def stochastic_d(self, period: int = 14, smooth: int = 3) -> pd.Series:
        return self.stochastic_k(period).rolling(smooth).mean()

    def obv(self) -> pd.Series:
        direction = self.close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        return (self.volume * direction).cumsum()

    def cci(self, period: int = 20) -> pd.Series:
        tp = (self.high + self.low + self.close) / 3
        sma = tp.rolling(period).mean()
        mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        return (tp - sma) / (0.015 * mad)

    def williams_r(self, period: int = 14) -> pd.Series:
        hh = self.high.rolling(period).max()
        ll = self.low.rolling(period).min()
        return -100 * (hh - self.close) / (hh - ll)

    def mfi(self, period: int = 14) -> pd.Series:
        tp = (self.high + self.low + self.close) / 3
        mf = tp * self.volume
        direction = tp.diff()
        pos_mf = mf.where(direction > 0, 0.0)
        neg_mf = mf.where(direction < 0, 0.0)
        pos_sum = pos_mf.rolling(period).sum()
        neg_sum = neg_mf.rolling(period).sum()
        mfr = pos_sum / neg_sum
        return 100 - 100 / (1 + mfr)

    def vwap(self) -> pd.Series:
        tp = (self.high + self.low + self.close) / 3
        return (tp * self.volume).cumsum() / self.volume.cumsum()

    def returns(self, period: int = 1) -> pd.Series:
        return self.close.pct_change(period)

    def volatility(self, period: int = 20) -> pd.Series:
        return self.close.pct_change().rolling(period).std() * np.sqrt(252)

    def volume_ratio(self, period: int = 20) -> pd.Series:
        return self.volume / self.volume.rolling(period).mean()


# ── Expression evaluator ─────────────────────────────────────────────

SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Gt: operator.gt,
    ast.Lt: operator.lt,
    ast.GtE: operator.ge,
    ast.LtE: operator.le,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.Invert: operator.invert,
    ast.USub: operator.neg,
}


def evaluate_expression(expr: str, candles: list[dict]) -> dict:
    """Evaluate a factor expression against OHLCV data.

    Returns:
        {
            "expression": str,
            "values": list[float],       # factor values per day
            "signal": list[bool],        # boolean signal per day
            "latest_value": float,
            "latest_signal": bool,
            "signal_count_30d": int,     # how many signals in last 30 days
            "dates": list[str],
        }
    """
    df = _build_df(candles)
    funcs = FactorFunctions(df)

    # preprocess: replace and/or/not with bitwise operators for pandas compatibility
    # wrap comparisons in parentheses to handle precedence: `a < 30 or b > 50` → `(a < 30) | (b > 50)`
    expr_clean = expr
    # wrap each comparison sub-expression before combining with and/or
    # strategy: split on and/or, wrap each part, rejoin
    for kw, op in [("and", "&"), ("or", "|")]:
        # match `keyword` surrounded by spaces, not inside strings
        parts = re.split(rf'\s+{kw}\s+', expr_clean)
        if len(parts) > 1:
            wrapped = []
            for p in parts:
                p = p.strip()
                # wrap if it contains a comparison operator and isn't already wrapped
                if any(op_tok in p for op_tok in ['<', '>', '<=', '>=', '==', '!=']) and not (p.startswith('(') and p.endswith(')')):
                    p = f'({p})'
                wrapped.append(p)
            expr_clean = f' {op} '.join(wrapped)
    expr_clean = re.sub(r'\b(not)\b', '~', expr_clean)

    # build namespace
    namespace = {
        "close": df["close"],
        "open": df["open"],
        "high": df["high"],
        "low": df["low"],
        "volume": df["volume"],
        "abs": abs,
        "min": min,
        "max": max,
        # factor functions
        "sma": funcs.sma,
        "ema": funcs.ema,
        "rsi": funcs.rsi,
        "macd": funcs.macd,
        "macd_cross": funcs.macd_cross,
        "bb_upper": funcs.bb_upper,
        "bb_lower": funcs.bb_lower,
        "bb_middle": funcs.bb_middle,
        "adx": funcs.adx,
        "atr": funcs.atr,
        "stochastic_k": funcs.stochastic_k,
        "stochastic_d": funcs.stochastic_d,
        "obv": funcs.obv,
        "cci": funcs.cci,
        "williams_r": funcs.williams_r,
        "mfi": funcs.mfi,
        "vwap": funcs.vwap,
        "returns": funcs.returns,
        "volatility": funcs.volatility,
        "volume_ratio": funcs.volume_ratio,
        "true": True,
        "false": False,
        "none": None,
    }

    try:
        result = eval(expr_clean, {"__builtins__": {}}, namespace)  # noqa: S307
    except Exception as e:
        return {"error": str(e), "expression": expr}

    # process result
    if isinstance(result, pd.Series):
        values = [round(float(v), 4) if pd.notna(v) else None for v in result]
        latest = values[-1] if values else None
        # check if it's a boolean series (signal)
        if result.dtype == bool or (hasattr(result, 'dtype') and result.dtype == np.bool_):
            bool_vals = [bool(v) if v is not None else False for v in values]
            return {
                "expression": expr,
                "type": "signal",
                "values": bool_vals,
                "latest_value": bool_vals[-1] if bool_vals else None,
                "latest_signal": bool_vals[-1] if bool_vals else False,
                "signal_count_30d": sum(bool_vals[-30:]),
                "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
            }
        else:
            return {
                "expression": expr,
                "type": "factor",
                "values": values,
                "latest_value": latest,
                "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
            }
    elif isinstance(result, (bool, np.bool_)):
        return {
            "expression": expr,
            "type": "signal",
            "values": [bool(result)],
            "latest_value": bool(result),
            "latest_signal": bool(result),
            "signal_count_30d": 1 if bool(result) else 0,
            "dates": [df["date"].iloc[-1].strftime("%Y-%m-%d")],
        }
    else:
        return {
            "expression": expr,
            "type": "scalar",
            "values": [float(result) if result is not None else None],
            "latest_value": float(result) if result is not None else None,
            "dates": [df["date"].iloc[-1].strftime("%Y-%m-%d")],
        }


# ── Built-in factor library ──────────────────────────────────────────

def compute_quintile_backtest(candles: list[dict], expression: str, holding_days: int = 5) -> dict:
    """Quintile analysis: split factor values into 5 groups, compare forward returns."""
    result = evaluate_expression(expression, candles)
    if result.get("error"):
        return {"error": result["error"]}
    if result.get("type") != "factor":
        return {"error": "Expression must return a numeric factor"}

    import numpy as np
    import pandas as pd

    df = pd.DataFrame(candles)
    factor_values = pd.Series(result["values"])
    forward_returns = df["close"].pct_change(holding_days).shift(-holding_days)

    # combine into dataframe and drop NaN
    combined = pd.DataFrame({"factor": factor_values, "fwd_return": forward_returns}).dropna()

    if len(combined) < 50:
        return {"error": "Not enough data for quintile analysis"}

    # split into quintiles
    combined["quintile"] = pd.qcut(combined["factor"], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")

    quintile_stats = []
    for q in sorted(combined["quintile"].unique()):
        group = combined[combined["quintile"] == q]
        quintile_stats.append({
            "quintile": int(q),
            "count": len(group),
            "avg_factor": round(float(group["factor"].mean()), 4),
            "avg_return": round(float(group["fwd_return"].mean()) * 100, 2),
            "median_return": round(float(group["fwd_return"].median()) * 100, 2),
            "win_rate": round(float((group["fwd_return"] > 0).mean()) * 100, 1),
        })

    # spread (top - bottom quintile)
    if len(quintile_stats) >= 2:
        spread = quintile_stats[-1]["avg_return"] - quintile_stats[0]["avg_return"]
    else:
        spread = 0

    return {
        "expression": expression,
        "holding_days": holding_days,
        "total_samples": len(combined),
        "quintiles": quintile_stats,
        "spread": round(spread, 2),
        "monotonicity": _check_monotonicity([q["avg_return"] for q in quintile_stats]),
    }


def compute_ic_analysis(candles: list[dict], expression: str, max_lag: int = 20) -> dict:
    """Rank IC analysis — correlation between factor values and forward returns at various lags."""
    result = evaluate_expression(expression, candles)
    if result.get("error"):
        return {"error": result["error"]}
    if result.get("type") != "factor":
        return {"error": "Expression must return a numeric factor"}

    import numpy as np
    import pandas as pd

    factor = pd.Series(result["values"])
    close = pd.DataFrame(candles)["close"]

    ic_by_lag = []
    for lag in range(1, min(max_lag + 1, len(close) // 4)):
        fwd_ret = close.pct_change(lag).shift(-lag)
        combined = pd.DataFrame({"factor": factor, "fwd_return": fwd_ret}).dropna()
        if len(combined) < 30:
            break
        # Rank IC (Spearman)
        ic = combined["factor"].corr(combined["fwd_return"], method="spearman")
        ic_by_lag.append({
            "lag": lag,
            "ic": round(float(ic), 4),
            "samples": len(combined),
        })

    if not ic_by_lag:
        return {"error": "Not enough data for IC analysis"}

    # find optimal lag
    best = max(ic_by_lag, key=lambda x: abs(x["ic"]))

    return {
        "expression": expression,
        "ic_by_lag": ic_by_lag,
        "best_lag": best["lag"],
        "best_ic": best["ic"],
        "avg_ic": round(float(np.mean([x["ic"] for x in ic_by_lag])), 4),
        "ic_positive_pct": round(float(np.mean([1 if x["ic"] > 0 else 0 for x in ic_by_lag])) * 100, 1),
    }


def compute_factor_decay(candles: list[dict], expression: str, periods: list[int] = None) -> dict:
    """Factor decay analysis — how predictive power changes across holding periods."""
    if periods is None:
        periods = [1, 2, 3, 5, 10, 20]

    result = evaluate_expression(expression, candles)
    if result.get("error"):
        return {"error": result["error"]}
    if result.get("type") != "factor":
        return {"error": "Expression must return a numeric factor"}

    import numpy as np
    import pandas as pd

    factor = pd.Series(result["values"])
    close = pd.DataFrame(candles)["close"]

    decay_data = []
    for period in periods:
        fwd_ret = close.pct_change(period).shift(-period)
        combined = pd.DataFrame({"factor": factor, "fwd_return": fwd_ret}).dropna()
        if len(combined) < 30:
            continue
        ic = combined["factor"].corr(combined["fwd_return"], method="spearman")
        # quintile spread
        combined["quintile"] = pd.qcut(combined["factor"], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
        q1_ret = combined[combined["quintile"] == 1]["fwd_return"].mean()
        q5_ret = combined[combined["quintile"] == 5]["fwd_return"].mean()
        spread = (q5_ret - q1_ret) * 100

        decay_data.append({
            "period": period,
            "ic": round(float(ic), 4),
            "quintile_spread": round(float(spread), 2),
        })

    if not decay_data:
        return {"error": "Not enough data for decay analysis"}

    # decay rate
    if len(decay_data) >= 2:
        first_ic = abs(decay_data[0]["ic"])
        last_ic = abs(decay_data[-1]["ic"])
        decay_rate = round((1 - last_ic / first_ic) * 100, 1) if first_ic > 0 else 0
    else:
        decay_rate = 0

    return {
        "expression": expression,
        "decay_data": decay_data,
        "decay_rate_pct": decay_rate,
        "half_life": _find_half_life(decay_data),
    }


def _find_half_life(decay_data: list[dict]) -> int | None:
    """Find the period where IC drops to half of its initial value."""
    if not decay_data:
        return None
    initial_ic = abs(decay_data[0]["ic"])
    half = initial_ic / 2
    for d in decay_data:
        if abs(d["ic"]) <= half:
            return d["period"]
    return None  # doesn't decay to half within tested periods


def _check_monotonicity(values: list[float]) -> str:
    """Check if values are monotonically increasing or decreasing."""
    if len(values) < 2:
        return "N/A"
    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    if all(d > 0 for d in diffs):
        return "increasing"
    elif all(d < 0 for d in diffs):
        return "decreasing"
    else:
        return "non-monotonic"


def compute_factor_distribution(candles: list[dict], expression: str, bins: int = 20) -> dict:
    """Compute histogram distribution of a factor expression's values."""
    result = evaluate_expression(expression, candles)
    if result.get("error"):
        return {"error": result["error"]}
    if result.get("type") != "factor":
        return {"error": "Expression must return a numeric factor, not a signal"}

    values = [v for v in result["values"] if v is not None]
    if not values:
        return {"error": "No valid values"}

    import numpy as np
    values = np.array(values)
    hist, bin_edges = np.histogram(values, bins=bins)

    distribution = []
    for i in range(len(hist)):
        distribution.append({
            "bin_start": round(float(bin_edges[i]), 4),
            "bin_end": round(float(bin_edges[i + 1]), 4),
            "count": int(hist[i]),
        })

    return {
        "expression": expression,
        "total_values": len(values),
        "mean": round(float(np.mean(values)), 4),
        "std": round(float(np.std(values)), 4),
        "min": round(float(np.min(values)), 4),
        "max": round(float(np.max(values)), 4),
        "percentile_25": round(float(np.percentile(values, 25)), 4),
        "percentile_50": round(float(np.percentile(values, 50)), 4),
        "percentile_75": round(float(np.percentile(values, 75)), 4),
        "distribution": distribution,
    }


def compute_multi_factor_score(candles: list[dict], expressions: list[str], weights: list[float] = None) -> dict:
    """Compute a weighted multi-factor composite score."""
    import numpy as np
    import pandas as pd

    if weights is None:
        weights = [1.0] * len(expressions)
    if len(weights) != len(expressions):
        return {"error": "weights length must match expressions length"}

    # evaluate each factor
    factor_values = {}
    for expr in expressions:
        result = evaluate_expression(expr, candles)
        if result.get("error"):
            return {"error": f"Error in '{expr}': {result['error']}"}
        if result.get("type") != "factor":
            return {"error": f"'{expr}' returns a signal, not a numeric factor"}
        factor_values[expr] = result["values"]

    # build DataFrame
    df = pd.DataFrame(factor_values)
    df = df.dropna()

    if len(df) < 10:
        return {"error": "Not enough overlapping data points"}

    # z-score normalize each factor
    normalized = (df - df.mean()) / df.std()

    # weighted combination
    weight_arr = np.array(weights)
    weight_arr = weight_arr / weight_arr.sum()  # normalize to sum=1
    composite = (normalized * weight_arr).sum(axis=1)

    # quintile analysis on composite
    fwd_ret = pd.DataFrame(candles)["close"].pct_change(5).shift(-5)
    combined = pd.DataFrame({"score": composite, "fwd_return": fwd_ret}).dropna()

    quintile_stats = []
    if len(combined) >= 50:
        combined["quintile"] = pd.qcut(combined["score"], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
        for q in sorted(combined["quintile"].unique()):
            group = combined[combined["quintile"] == q]
            quintile_stats.append({
                "quintile": int(q),
                "avg_return": round(float(group["fwd_return"].mean()) * 100, 2),
                "win_rate": round(float((group["fwd_return"] > 0).mean()) * 100, 1),
            })

    return {
        "expressions": expressions,
        "weights": [round(w, 2) for w in weights],
        "n_samples": len(df),
        "composite_mean": round(float(composite.mean()), 4),
        "composite_std": round(float(composite.std()), 4),
        "latest_score": round(float(composite.iloc[-1]), 4),
        "latest_quintile": int(pd.qcut(composite, 5, labels=[1, 2, 3, 4, 5], duplicates="drop").iloc[-1]) if len(composite) >= 5 else None,
        "quintile_analysis": quintile_stats,
        "values": [round(float(v), 4) for v in composite.tolist()],
        "dates": [str(c["date"]) for c in candles[-len(composite):]],
    }


def compute_neutralization(candles: list[dict], expression: str) -> dict:
    """Neutralize a factor by removing trend/mean exposure (de-mean and de-trend)."""
    import numpy as np
    import pandas as pd

    result = evaluate_expression(expression, candles)
    if result.get("error"):
        return {"error": result["error"]}
    if result.get("type") != "factor":
        return {"error": "Expression must return a numeric factor"}

    values = pd.Series(result["values"]).dropna()
    if len(values) < 20:
        return {"error": "Not enough data"}

    # de-mean (remove constant bias)
    demeaned = values - values.mean()

    # de-trend (remove linear trend)
    x = np.arange(len(demeaned))
    coeffs = np.polyfit(x, demeaned.values, 1)
    trend = np.polyval(coeffs, x)
    detrended = demeaned - trend

    # rolling z-score (adaptive normalization)
    window = min(60, len(detrended) // 3)
    rolling_mean = detrended.rolling(window, min_periods=10).mean()
    rolling_std = detrended.rolling(window, min_periods=10).std()
    neutralized = (detrended - rolling_mean) / rolling_std.replace(0, 1)

    return {
        "expression": expression,
        "original_mean": round(float(values.mean()), 4),
        "original_std": round(float(values.std()), 4),
        "trend_slope": round(float(coeffs[0]), 6),
        "neutralized_mean": round(float(neutralized.dropna().mean()), 4),
        "neutralized_std": round(float(neutralized.dropna().std()), 4),
        "values": [round(float(v), 4) if not np.isnan(v) else None for v in neutralized.tolist()],
        "dates": [str(c["date"]) for c in candles[-len(neutralized):]],
    }


def compute_orthogonalization(candles: list[dict], expressions: list[str]) -> dict:
    """Remove multicollinearity between factors via Gram-Schmidt orthogonalization."""
    import numpy as np
    import pandas as pd

    # evaluate each factor
    factor_values = {}
    for expr in expressions:
        result = evaluate_expression(expr, candles)
        if result.get("error"):
            return {"error": f"Error in '{expr}': {result['error']}"}
        if result.get("type") != "factor":
            return {"error": f"'{expr}' returns a signal, not a numeric factor"}
        factor_values[expr] = result["values"]

    df = pd.DataFrame(factor_values).dropna()
    if len(df) < 10:
        return {"error": "Not enough data"}

    # z-score normalize
    normalized = (df - df.mean()) / df.std()
    original_corr = normalized.corr()

    # Gram-Schmidt orthogonalization
    orthogonal = pd.DataFrame(index=df.index)
    basis = []

    for i, col in enumerate(expressions):
        v = normalized[col].values.copy()
        # subtract projection onto all previous basis vectors
        for b in basis:
            proj = np.dot(v, b) / np.dot(b, b)
            v = v - proj * b
        # skip if near-zero (linearly dependent)
        if np.linalg.norm(v) < 1e-10:
            continue
        basis.append(v)
        orthogonal[f"ortho_{i}"] = v

    # correlation of orthogonalized factors (should be ~0)
    ortho_corr = orthogonal.corr()

    return {
        "original_factors": expressions,
        "orthogonal_count": len(basis),
        "removed_count": len(expressions) - len(basis),
        "original_correlation": {
            "factors": expressions,
            "matrix": [[round(float(original_corr.iloc[i, j]), 4) for j in range(len(expressions))] for i in range(len(expressions))],
        },
        "orthogonal_correlation": {
            "factors": list(orthogonal.columns),
            "matrix": [[round(float(ortho_corr.iloc[i, j]), 4) for j in range(len(orthogonal.columns))] for i in range(len(orthogonal.columns))],
        },
        "orthogonal_values": {col: [round(float(v), 4) for v in orthogonal[col].tolist()] for col in orthogonal.columns},
    }


NUMERIC_FACTORS = [
    "rsi(14)",
    "stochastic_k(14)",
    "cci(20)",
    "williams_r(14)",
    "mfi(14)",
    "adx(14)",
    "atr(14)",
    "volatility(20)",
    "volume_ratio(20)",
    "returns(20)",
]


def compute_factor_correlation(candles: list[dict], factor_names: list[str] = None) -> dict:
    """Compute correlation matrix between multiple factor expressions.

    Returns: {factors: [...], matrix: [[...]], dates: [...]}
    """
    if factor_names is None:
        factor_names = NUMERIC_FACTORS

    # evaluate each factor
    factor_values = {}
    for expr in factor_names:
        result = evaluate_expression(expr, candles)
        if result.get("error") or result.get("type") != "factor":
            continue
        factor_values[expr] = result["values"]

    if len(factor_values) < 2:
        return {"error": "Need at least 2 valid numeric factors", "factors": [], "matrix": []}

    # build DataFrame and compute correlation
    df = pd.DataFrame(factor_values)
    df = df.dropna()
    corr = df.corr()

    factors = list(corr.columns)
    matrix = []
    for f in factors:
        row = [round(corr.loc[f, f2], 4) for f2 in factors]
        matrix.append(row)

    return {
        "factors": factors,
        "matrix": matrix,
        "n_samples": len(df),
    }


FACTOR_CATEGORIES = {
    "Momentum": "https://en.wikipedia.org/wiki/Momentum_(technical_analysis)",
    "Mean Reversion": "https://en.wikipedia.org/wiki/Mean_reversion_(finance)",
    "Trend": "https://en.wikipedia.org/wiki/Trend_following",
    "Volatility": "https://en.wikipedia.org/wiki/Volatility_(finance)",
    "Volume": "https://en.wikipedia.org/wiki/Volume_analysis",
    "Breakout": "https://en.wikipedia.org/wiki/Breakout_(technical_analysis)",
    "Composite": "Multi-factor combinations",
}

BUILTIN_FACTORS = [
    # ── Momentum ──
    {
        "name": "RSI Oversold",
        "category": "Momentum",
        "expression": "rsi(14) < 30",
        "description": "RSI below 30 indicates oversold conditions — potential bounce",
        "signal_type": "buy",
    },
    {
        "name": "RSI Overbought",
        "category": "Momentum",
        "expression": "rsi(14) > 70",
        "description": "RSI above 70 indicates overbought conditions — potential pullback",
        "signal_type": "sell",
    },
    {
        "name": "RSI Divergence (Bullish)",
        "category": "Momentum",
        "expression": "rsi(14) < 40 and rsi(14) > rsi(14)",
        "description": "RSI making higher lows while price makes lower lows",
        "signal_type": "buy",
    },
    {
        "name": "MACD Bullish Cross",
        "category": "Momentum",
        "expression": "macd_cross('bullish')",
        "description": "MACD histogram crosses above zero — momentum shifting up",
        "signal_type": "buy",
    },
    {
        "name": "MACD Bearish Cross",
        "category": "Momentum",
        "expression": "macd_cross('bearish')",
        "description": "MACD histogram crosses below zero — momentum shifting down",
        "signal_type": "sell",
    },
    {
        "name": "Stochastic Oversold",
        "category": "Momentum",
        "expression": "stochastic_k(14) < 20",
        "description": "Stochastic %K below 20 — oversold territory",
        "signal_type": "buy",
    },
    {
        "name": "Stochastic Overbought",
        "category": "Momentum",
        "expression": "stochastic_k(14) > 80",
        "description": "Stochastic %K above 80 — overbought territory",
        "signal_type": "sell",
    },
    {
        "name": "Williams %R Oversold",
        "category": "Momentum",
        "expression": "williams_r(14) < -80",
        "description": "Williams %R below -80 — oversold",
        "signal_type": "buy",
    },
    {
        "name": "CCI Extreme Low",
        "category": "Momentum",
        "expression": "cci(20) < -100",
        "description": "CCI below -100 — oversold cyclical low",
        "signal_type": "buy",
    },
    {
        "name": "N-Day Momentum",
        "category": "Momentum",
        "expression": "returns(20) > 0.1",
        "description": "20-day return exceeds 10% — strong momentum",
        "signal_type": "buy",
    },

    # ── Mean Reversion ──
    {
        "name": "Price Below Lower BB",
        "category": "Mean Reversion",
        "expression": "close < bb_lower(20, 2)",
        "description": "Price dropped below Bollinger lower band — mean reversion opportunity",
        "signal_type": "buy",
    },
    {
        "name": "Price Above Upper BB",
        "category": "Mean Reversion",
        "expression": "close > bb_upper(20, 2)",
        "description": "Price above Bollinger upper band — potential pullback",
        "signal_type": "sell",
    },
    {
        "name": "Bollinger Squeeze",
        "category": "Volatility",
        "expression": "(bb_upper(20, 2) - bb_lower(20, 2)) / bb_middle(20) < 0.05",
        "description": "Bollinger bandwidth is very narrow — breakout imminent",
        "signal_type": "watch",
    },

    # ── Trend ──
    {
        "name": "Strong Trend (ADX)",
        "category": "Trend",
        "expression": "adx(14) > 25",
        "description": "ADX above 25 indicates a strong trend in progress",
        "signal_type": "watch",
    },
    {
        "name": "Weak Trend",
        "category": "Trend",
        "expression": "adx(14) < 20",
        "description": "ADX below 20 — no clear trend, ranging market",
        "signal_type": "neutral",
    },
    {
        "name": "Price Above VWAP",
        "category": "Trend",
        "expression": "close > vwap()",
        "description": "Price trading above VWAP — bullish intraday bias",
        "signal_type": "buy",
    },
    {
        "name": "Price Below VWAP",
        "category": "Trend",
        "expression": "close < vwap()",
        "description": "Price trading below VWAP — bearish intraday bias",
        "signal_type": "sell",
    },

    # ── Volatility ──
    {
        "name": "High Volatility",
        "category": "Volatility",
        "expression": "volatility(20) > 0.4",
        "description": "Annualized volatility above 40% — high risk environment",
        "signal_type": "watch",
    },
    {
        "name": "Low Volatility",
        "category": "Volatility",
        "expression": "volatility(20) < 0.15",
        "description": "Annualized volatility below 15% — calm market, potential breakout setup",
        "signal_type": "watch",
    },

    # ── Volume ──
    {
        "name": "Volume Spike",
        "category": "Volume",
        "expression": "volume > sma(volume, 20) * 1.5",
        "description": "Volume is 50% above its 20-day average — institutional activity",
        "signal_type": "watch",
    },
    {
        "name": "MFI Oversold",
        "category": "Volume",
        "expression": "mfi(14) < 20",
        "description": "Money Flow Index below 20 — money outflow, potential reversal",
        "signal_type": "buy",
    },
    {
        "name": "MFI Overbought",
        "category": "Volume",
        "expression": "mfi(14) > 80",
        "description": "Money Flow Index above 80 — money inflow, potential topping",
        "signal_type": "sell",
    },
    {
        "name": "OBV Divergence",
        "category": "Volume",
        "expression": "obv() > ema(obv(), 20)",
        "description": "OBV above its 20 EMA — accumulation pattern",
        "signal_type": "buy",
    },

    # ── Breakout ──
    {
        "name": "52-Week High Breakout",
        "category": "Breakout",
        "expression": "close >= returns(250) * close * 0.98",
        "description": "Price near 52-week high — potential breakout",
        "signal_type": "buy",
    },
    {
        "name": "Price Crosses SMA 200",
        "category": "Breakout",
        "expression": "close > sma(close, 200)",
        "description": "Price above 200-day SMA — long-term bullish",
        "signal_type": "buy",
    },

    # ── Composite (multi-factor) ──
    {
        "name": "Oversold Combo",
        "category": "Composite",
        "expression": "rsi(14) < 35 and stochastic_k(14) < 25 and mfi(14) < 30",
        "description": "RSI + Stochastic + MFI all oversold — strong buy signal",
        "signal_type": "buy",
    },
    {
        "name": "Overbought Combo",
        "category": "Composite",
        "expression": "rsi(14) > 65 and stochastic_k(14) > 75 and mfi(14) > 70",
        "description": "RSI + Stochastic + MFI all overbought — strong sell signal",
        "signal_type": "sell",
    },
    {
        "name": "Trend + Volume",
        "category": "Composite",
        "expression": "adx(14) > 25 and volume > sma(volume, 20) * 1.3",
        "description": "Strong trend with volume confirmation",
        "signal_type": "buy",
    },
    {
        "name": "Williams %R Oversold",
        "category": "Momentum",
        "expression": "williams_r(14) < -80",
        "description": "Williams %R below -80 — oversold",
    },
    {
        "name": "CCI Extreme",
        "category": "Momentum",
        "expression": "cci(20) > 200",
        "description": "CCI above 200 — extreme overbought",
    },
]
