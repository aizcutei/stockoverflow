"""Technical indicator calculations with support/resistance and signals.

All functions accept a pandas DataFrame with columns: date, open, high, low, close, volume.
They return a dict ready to be serialized as JSON.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── helpers ──────────────────────────────────────────────────────────────


def _build_df(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _round(v, n=4):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    return round(float(v), n)


def _pct(a, b):
    """Percentage difference a vs b."""
    if b == 0:
        return None
    return round((a - b) / abs(b) * 100, 2)


# ── 1. MACD ─────────────────────────────────────────────────────────────


def calc_macd(candles: list[dict]) -> dict:
    """MACD (12/26/9) with crossover signal, support/resistance on histogram."""
    df = _build_df(candles)
    close = df["close"]

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    cur_macd = _round(macd_line.iloc[-1])
    cur_signal = _round(signal_line.iloc[-1])
    cur_hist = _round(histogram.iloc[-1])

    # crossover detection (last 3 bars)
    prev_hist = histogram.iloc[-4:-1]
    cross = "none"
    if len(prev_hist) >= 1:
        if cur_hist > 0 and prev_hist.iloc[-1] <= 0:
            cross = "bullish"
        elif cur_hist < 0 and prev_hist.iloc[-1] >= 0:
            cross = "bearish"

    # support = recent histogram low, resistance = recent histogram high
    recent_hist = histogram.tail(60)
    support = _round(recent_hist.min())
    resistance = _round(recent_hist.max())

    # signal
    if cross == "bullish" or (cur_macd is not None and cur_macd > cur_signal):
        signal = "BUY"
        strength = min(abs(cur_hist or 0) * 10, 100)
    elif cross == "bearish" or (cur_macd is not None and cur_macd < cur_signal):
        signal = "SELL"
        strength = min(abs(cur_hist or 0) * 10, 100)
    else:
        signal = "NEUTRAL"
        strength = 0

    return {
        "name": "MACD",
        "params": "12/26/9",
        "values": {
            "macd": cur_macd,
            "signal": cur_signal,
            "histogram": cur_hist,
            "crossover": cross,
        },
        "levels": {"support": support, "resistance": resistance},
        "signal": signal,
        "strength": round(strength, 1),
        "series": {
            "macd": [_round(v) for v in macd_line.tolist()],
            "signal": [_round(v) for v in signal_line.tolist()],
            "histogram": [_round(v) for v in histogram.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 2. Bollinger Bands ─────────────────────────────────────────────────


def calc_bollinger(candles: list[dict]) -> dict:
    """Bollinger Bands (20, 2). Support = lower band, resistance = upper band."""
    df = _build_df(candles)
    close = df["close"]
    window = 20
    sma = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    bandwidth = (upper - lower) / sma * 100
    pct_b = (close - lower) / (upper - lower)  # %B

    cur_close = _round(close.iloc[-1])
    cur_upper = _round(upper.iloc[-1])
    cur_lower = _round(lower.iloc[-1])
    cur_sma = _round(sma.iloc[-1])
    cur_bw = _round(bandwidth.iloc[-1], 2)
    cur_pctb = _round(pct_b.iloc[-1], 4)

    # squeeze detection
    bw_vals = bandwidth.dropna()
    is_squeeze = bool(cur_bw is not None and len(bw_vals) > 60 and cur_bw < bw_vals.tail(60).quantile(0.2))

    # signal
    if cur_pctb is not None:
        if cur_pctb < 0.05:
            signal, reason = "BUY", "Price at lower band — oversold"
        elif cur_pctb > 0.95:
            signal, reason = "SELL", "Price at upper band — overbought"
        elif is_squeeze:
            signal, reason = "WATCH", "Bollinger squeeze — breakout imminent"
        else:
            signal, reason = "NEUTRAL", "Price within bands"
    else:
        signal, reason = "NEUTRAL", "Insufficient data"
        cur_pctb = 0

    strength = abs((cur_pctb or 0.5) - 0.5) * 200  # 0 at mid, 100 at extremes

    return {
        "name": "Bollinger Bands",
        "params": "20/2σ",
        "values": {
            "upper": cur_upper,
            "middle": cur_sma,
            "lower": cur_lower,
            "bandwidth": cur_bw,
            "percent_b": cur_pctb,
            "squeeze": is_squeeze,
        },
        "levels": {"support": cur_lower, "resistance": cur_upper},
        "signal": signal,
        "strength": round(strength, 1),
        "reason": reason,
        "series": {
            "upper": [_round(v) for v in upper.tolist()],
            "middle": [_round(v) for v in sma.tolist()],
            "lower": [_round(v) for v in lower.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 3. Ichimoku Cloud ──────────────────────────────────────────────────


def calc_ichimoku(candles: list[dict]) -> dict:
    """Ichimoku Kinko Hyo (9/26/52/26). Support = cloud bottom, resistance = cloud top."""
    df = _build_df(candles)
    high, low, close = df["high"], df["low"], df["close"]

    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    chikou = close.shift(-26)

    cur_close = _round(close.iloc[-1])
    cur_tenkan = _round(tenkan.iloc[-1])
    cur_kijun = _round(kijun.iloc[-1])
    cur_senkou_a = _round(senkou_a.iloc[-1])
    cur_senkou_b = _round(senkou_b.iloc[-1])

    # cloud boundaries = support/resistance
    cloud_vals = [v for v in [cur_senkou_a, cur_senkou_b] if v is not None]
    cloud_top = max(cloud_vals) if cloud_vals else cur_close
    cloud_bottom = min(cloud_vals) if cloud_vals else cur_close

    # TK cross
    tk_cross = "none"
    if len(tenkan.dropna()) >= 2 and len(kijun.dropna()) >= 2:
        prev_t, prev_k = tenkan.iloc[-2], kijun.iloc[-2]
        if cur_tenkan > cur_kijun and prev_t <= prev_k:
            tk_cross = "bullish"
        elif cur_tenkan < cur_kijun and prev_t >= prev_k:
            tk_cross = "bearish"

    # price vs cloud
    if cur_close is not None:
        if cur_close > cloud_top:
            cloud_pos = "above"
        elif cur_close < cloud_bottom:
            cloud_pos = "below"
        else:
            cloud_pos = "inside"
    else:
        cloud_pos = "unknown"

    # signal
    bullish_points = 0
    if cloud_pos == "above":
        bullish_points += 2
    elif cloud_pos == "below":
        bullish_points -= 2
    if tk_cross == "bullish":
        bullish_points += 1
    elif tk_cross == "bearish":
        bullish_points -= 1
    if cur_tenkan and cur_kijun and cur_tenkan > cur_kijun:
        bullish_points += 1

    if bullish_points >= 2:
        signal = "BUY"
    elif bullish_points <= -2:
        signal = "SELL"
    else:
        signal = "NEUTRAL"
    strength = min(abs(bullish_points) * 25, 100)

    return {
        "name": "Ichimoku",
        "params": "9/26/52/26",
        "values": {
            "tenkan": cur_tenkan,
            "kijun": cur_kijun,
            "senkou_a": cur_senkou_a,
            "senkou_b": cur_senkou_b,
            "tk_cross": tk_cross,
            "cloud_position": cloud_pos,
        },
        "levels": {"support": cloud_bottom, "resistance": cloud_top},
        "signal": signal,
        "strength": round(strength, 1),
        "series": {
            "tenkan": [_round(v) for v in tenkan.tolist()],
            "kijun": [_round(v) for v in kijun.tolist()],
            "senkou_a": [_round(v) for v in senkou_a.tolist()],
            "senkou_b": [_round(v) for v in senkou_b.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 4. Tom Demark Sequential ───────────────────────────────────────────


def calc_demark(candles: list[dict]) -> dict:
    """Tom Demark Sequential — setup (9-bar) and countdown (13-bar).

    Buy setup: 9 consecutive closes < close[4 bars ago]
    Sell setup: 9 consecutive closes > close[4 bars ago]
    Countdown extends to 13 after a setup completes.
    """
    df = _build_df(candles)
    close = df["close"].values
    n = len(close)

    # --- Setup phase ---
    buy_count = 0
    sell_count = 0
    buy_counts = np.zeros(n, dtype=int)
    sell_counts = np.zeros(n, dtype=int)

    for i in range(4, n):
        if close[i] < close[i - 4]:
            buy_count += 1
            sell_count = 0
        elif close[i] > close[i - 4]:
            sell_count += 1
            buy_count = 0
        else:
            buy_count = 0
            sell_count = 0
        buy_counts[i] = buy_count
        sell_counts[i] = sell_count

    cur_buy = int(buy_counts[-1])
    cur_sell = int(sell_counts[-1])

    # look for completed setups in last 30 bars
    recent_buy_setup = bool(np.any(buy_counts[-30:] >= 9))
    recent_sell_setup = bool(np.any(sell_counts[-30:] >= 9))

    # find the bar where setup completed
    buy_setup_bar = None
    sell_setup_bar = None
    for i in range(max(0, n - 30), n):
        if buy_counts[i] >= 9:
            buy_setup_bar = i
        if sell_counts[i] >= 9:
            sell_setup_bar = i

    # countdown after setup
    buy_cd = 0
    sell_cd = 0
    if buy_setup_bar is not None:
        ref_low = df["low"].iloc[buy_setup_bar]
        for i in range(buy_setup_bar + 1, n):
            if close[i] < ref_low:
                buy_cd += 1
            if buy_cd >= 13:
                break
    if sell_setup_bar is not None:
        ref_high = df["high"].iloc[sell_setup_bar]
        for i in range(sell_setup_bar + 1, n):
            if close[i] > ref_high:
                sell_cd += 1
            if sell_cd >= 13:
                break

    # support/resistance
    recent = df.tail(20)
    support = _round(float(recent["low"].min()))
    resistance = _round(float(recent["high"].max()))

    # signal
    if buy_cd >= 13:
        signal, reason = "BUY", "TD Countdown 13 buy — exhaustion low"
    elif sell_cd >= 13:
        signal, reason = "SELL", "TD Countdown 13 sell — exhaustion high"
    elif cur_buy >= 9:
        signal, reason = "BUY", "TD 9 buy setup completed"
    elif cur_sell >= 9:
        signal, reason = "SELL", "TD 9 sell setup completed"
    elif cur_buy >= 7:
        signal, reason = "WATCH", f"Buy setup building ({cur_buy}/9)"
    elif cur_sell >= 7:
        signal, reason = "WATCH", f"Sell setup building ({cur_sell}/9)"
    else:
        signal, reason = "NEUTRAL", "No active setup"
        cur_buy = 0
        cur_sell = 0

    strength_map = {9: 80, 8: 60, 7: 40}
    if signal == "BUY":
        strength = strength_map.get(cur_buy, 100 if buy_cd >= 13 else 50)
    elif signal == "SELL":
        strength = strength_map.get(cur_sell, 100 if sell_cd >= 13 else 50)
    else:
        strength = 0

    return {
        "name": "TD Sequential",
        "params": "9-setup / 13-countdown",
        "values": {
            "buy_setup": cur_buy,
            "sell_setup": cur_sell,
            "buy_countdown": buy_cd,
            "sell_countdown": sell_cd,
            "recent_buy_9": recent_buy_setup,
            "recent_sell_9": recent_sell_setup,
        },
        "levels": {"support": support, "resistance": resistance},
        "signal": signal,
        "strength": round(strength, 1),
        "reason": reason,
        "series": {
            "buy_counts": buy_counts.tolist(),
            "sell_counts": sell_counts.tolist(),
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 5. RSI ──────────────────────────────────────────────────────────────


def calc_rsi(candles: list[dict], period: int = 14) -> dict:
    """RSI (14). Overbought >70, Oversold <30."""
    df = _build_df(candles)
    close = df["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)

    cur_rsi = _round(rsi.iloc[-1], 2)

    if cur_rsi is not None:
        if cur_rsi < 30:
            signal, reason = "BUY", f"RSI {cur_rsi} — oversold"
            strength = (30 - cur_rsi) / 30 * 100
        elif cur_rsi > 70:
            signal, reason = "SELL", f"RSI {cur_rsi} — overbought"
            strength = (cur_rsi - 70) / 30 * 100
        else:
            signal, reason = "NEUTRAL", f"RSI {cur_rsi} — normal range"
            strength = 0
    else:
        signal, reason, strength = "NEUTRAL", "Insufficient data", 0

    return {
        "name": "RSI",
        "params": f"{period}",
        "values": {"rsi": cur_rsi},
        "levels": {"support": 30, "resistance": 70},
        "signal": signal,
        "strength": round(min(strength, 100), 1),
        "reason": reason,
        "series": {
            "rsi": [_round(v, 2) for v in rsi.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 6. Stochastic Oscillator ───────────────────────────────────────────


def calc_stochastic(candles: list[dict], k_period: int = 14, d_period: int = 3) -> dict:
    """Stochastic %K/%D (14,3,3). Overbought >80, Oversold <20."""
    df = _build_df(candles)
    high, low, close = df["high"], df["low"], df["close"]

    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(d_period).mean()

    cur_k = _round(k.iloc[-1], 2)
    cur_d = _round(d.iloc[-1], 2)

    # crossover
    cross = "none"
    if len(k.dropna()) >= 2 and len(d.dropna()) >= 2:
        if cur_k > cur_d and k.iloc[-2] <= d.iloc[-2]:
            cross = "bullish"
        elif cur_k < cur_d and k.iloc[-2] >= d.iloc[-2]:
            cross = "bearish"

    if cur_k is not None and cur_d is not None:
        if cur_k < 20 and cur_d < 20:
            signal, reason = "BUY", f"%K {cur_k} / %D {cur_d} — oversold zone"
            strength = (20 - min(cur_k, cur_d)) / 20 * 100
        elif cur_k > 80 and cur_d > 80:
            signal, reason = "SELL", f"%K {cur_k} / %D {cur_d} — overbought zone"
            strength = (max(cur_k, cur_d) - 80) / 20 * 100
        elif cross == "bullish" and cur_k < 50:
            signal, reason = "BUY", "Bullish crossover in lower zone"
            strength = 50
        elif cross == "bearish" and cur_k > 50:
            signal, reason = "SELL", "Bearish crossover in upper zone"
            strength = 50
        else:
            signal, reason = "NEUTRAL", f"%K {cur_k} / %D {cur_d}"
            strength = 0
    else:
        signal, reason, strength = "NEUTRAL", "Insufficient data", 0

    return {
        "name": "Stochastic",
        "params": f"{k_period}/{d_period}/{d_period}",
        "values": {"k": cur_k, "d": cur_d, "crossover": cross},
        "levels": {"support": 20, "resistance": 80},
        "signal": signal,
        "strength": round(min(strength, 100), 1),
        "reason": reason,
        "series": {
            "k": [_round(v, 2) for v in k.tolist()],
            "d": [_round(v, 2) for v in d.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 7. ADX (Average Directional Index) ─────────────────────────────────


def calc_adx(candles: list[dict], period: int = 14) -> dict:
    """ADX (14). Trend strength: >25 = trending, >50 = strong trend."""
    df = _build_df(candles)
    high, low, close = df["high"], df["low"], df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(span=period, adjust=False).mean()

    cur_adx = _round(adx.iloc[-1], 2)
    cur_plus = _round(plus_di.iloc[-1], 2)
    cur_minus = _round(minus_di.iloc[-1], 2)

    if cur_adx is not None:
        if cur_adx > 25 and cur_plus and cur_minus:
            if cur_plus > cur_minus:
                signal = "BUY"
                reason = f"ADX {cur_adx} — uptrend (+DI {cur_plus} > -DI {cur_minus})"
            else:
                signal = "SELL"
                reason = f"ADX {cur_adx} — downtrend (-DI {cur_minus} > +DI {cur_plus})"
            strength = min((cur_adx - 20) / 30 * 100, 100)
        elif cur_adx < 20:
            signal, reason = "NEUTRAL", f"ADX {cur_adx} — no trend (ranging market)"
            strength = 0
        else:
            signal, reason = "WATCH", f"ADX {cur_adx} — weak trend forming"
            strength = (cur_adx - 20) / 5 * 50
    else:
        signal, reason, strength = "NEUTRAL", "Insufficient data", 0

    return {
        "name": "ADX",
        "params": f"{period}",
        "values": {"adx": cur_adx, "plus_di": cur_plus, "minus_di": cur_minus},
        "levels": {"support": 20, "resistance": 50},
        "signal": signal,
        "strength": round(min(max(strength, 0), 100), 1),
        "reason": reason,
        "series": {
            "adx": [_round(v, 2) for v in adx.tolist()],
            "plus_di": [_round(v, 2) for v in plus_di.tolist()],
            "minus_di": [_round(v, 2) for v in minus_di.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 8. VWAP (Volume Weighted Average Price) ────────────────────────────


def calc_vwap(candles: list[dict]) -> dict:
    """VWAP — volume-weighted average price. Cumulative anchor to start of data."""
    df = _build_df(candles)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (tp * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    vwap = cum_tp_vol / cum_vol

    cur_close = _round(df["close"].iloc[-1], 4)
    cur_vwap = _round(vwap.iloc[-1], 4)

    # deviation bands (±1%, ±2%)
    upper1 = _round(cur_vwap * 1.01, 4) if cur_vwap else None
    lower1 = _round(cur_vwap * 0.99, 4) if cur_vwap else None
    upper2 = _round(cur_vwap * 1.02, 4) if cur_vwap else None
    lower2 = _round(cur_vwap * 0.98, 4) if cur_vwap else None

    if cur_close is not None and cur_vwap is not None:
        pct = (cur_close - cur_vwap) / cur_vwap * 100
        if cur_close < lower2:
            signal, reason = "BUY", f"Price {round(pct,1)}% below VWAP — deep discount"
            strength = min(abs(pct) * 15, 100)
        elif cur_close < cur_vwap:
            signal, reason = "WATCH", f"Price {round(pct,1)}% below VWAP — discount"
            strength = min(abs(pct) * 10, 60)
        elif cur_close > upper2:
            signal, reason = "SELL", f"Price +{round(pct,1)}% above VWAP — extended"
            strength = min(abs(pct) * 15, 100)
        elif cur_close > cur_vwap:
            signal, reason = "WATCH", f"Price +{round(pct,1)}% above VWAP — premium"
            strength = min(abs(pct) * 10, 60)
        else:
            signal, reason = "NEUTRAL", "Price at VWAP"
            strength = 0
    else:
        signal, reason, strength = "NEUTRAL", "Insufficient data", 0

    return {
        "name": "VWAP",
        "params": "Cumulative",
        "values": {"vwap": cur_vwap, "upper_1pct": upper1, "lower_1pct": lower1},
        "levels": {"support": lower2, "resistance": upper2},
        "signal": signal,
        "strength": round(strength, 1),
        "reason": reason,
        "series": {
            "vwap": [_round(v, 4) for v in vwap.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 9. ATR (Average True Range) ────────────────────────────────────────


def calc_atr(candles: list[dict], period: int = 14) -> dict:
    """ATR (14). Volatility measure. Support = current_close - ATR, Resistance = current_close + ATR."""
    df = _build_df(candles)
    high, low, close = df["high"], df["low"], df["close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    cur_atr = _round(atr.iloc[-1], 4)
    cur_close = _round(close.iloc[-1], 4)
    atr_pct = round(cur_atr / cur_close * 100, 2) if cur_atr and cur_close else None

    support = _round(cur_close - cur_atr) if cur_close and cur_atr else None
    resistance = _round(cur_close + cur_atr) if cur_close and cur_atr else None

    # ATR itself doesn't give buy/sell, but high ATR = volatile, low ATR = calm
    if atr_pct is not None:
        if atr_pct > 5:
            signal, reason = "WATCH", f"ATR {atr_pct}% — very high volatility, use wider stops"
            strength = min((atr_pct - 3) * 20, 100)
        elif atr_pct > 3:
            signal, reason = "WATCH", f"ATR {atr_pct}% — elevated volatility"
            strength = (atr_pct - 2) * 20
        else:
            signal, reason = "NEUTRAL", f"ATR {atr_pct}% — normal volatility"
            strength = 0
    else:
        signal, reason, strength = "NEUTRAL", "Insufficient data", 0

    return {
        "name": "ATR",
        "params": f"{period}",
        "values": {"atr": cur_atr, "atr_pct": atr_pct},
        "levels": {"support": support, "resistance": resistance},
        "signal": signal,
        "strength": round(min(strength, 100), 1),
        "reason": reason,
        "series": {
            "atr": [_round(v, 4) for v in atr.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 10. OBV (On-Balance Volume) ────────────────────────────────────────


def calc_obv(candles: list[dict]) -> dict:
    """OBV — on-balance volume. Volume momentum confirmation."""
    df = _build_df(candles)
    close = df["close"]
    volume = df["volume"]

    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (volume * direction).cumsum()
    obv_sma = obv.rolling(20).mean()

    cur_obv = _round(obv.iloc[-1], 0)
    cur_sma = _round(obv_sma.iloc[-1], 0)
    price_trend = "up" if close.iloc[-1] > close.iloc[-20] else "down"
    obv_trend = "up" if obv.iloc[-1] > obv.iloc[-20] else "down"

    # divergence detection
    divergence = "none"
    if price_trend == "up" and obv_trend == "down":
        divergence = "bearish"  # price up, volume down → weak
    elif price_trend == "down" and obv_trend == "up":
        divergence = "bullish"  # price down, volume up → accumulation

    if divergence == "bullish":
        signal, reason = "BUY", "Bullish OBV divergence — accumulation detected"
        strength = 65
    elif divergence == "bearish":
        signal, reason = "SELL", "Bearish OBV divergence — distribution detected"
        strength = 65
    elif obv_trend == "up" and price_trend == "up":
        signal, reason = "BUY", "OBV confirms uptrend"
        strength = 40
    elif obv_trend == "down" and price_trend == "down":
        signal, reason = "SELL", "OBV confirms downtrend"
        strength = 40
    else:
        signal, reason = "NEUTRAL", "OBV neutral"
        strength = 0

    return {
        "name": "OBV",
        "params": "Volume",
        "values": {"obv": cur_obv, "obv_sma_20": cur_sma, "divergence": divergence},
        "levels": {"support": None, "resistance": None},
        "signal": signal,
        "strength": round(strength, 1),
        "reason": reason,
        "series": {
            "obv": [_round(v, 0) for v in obv.tolist()],
            "obv_sma": [_round(v, 0) for v in obv_sma.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 11. CCI (Commodity Channel Index) ──────────────────────────────────


def calc_cci(candles: list[dict], period: int = 20) -> dict:
    """CCI (20). Overbought >100, Oversold <-100. Extreme >200 / <-200."""
    df = _build_df(candles)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    cci = (tp - sma) / (0.015 * mad)

    cur_cci = _round(cci.iloc[-1], 2)

    if cur_cci is not None:
        if cur_cci < -200:
            signal, reason = "BUY", f"CCI {cur_cci} — extreme oversold"
            strength = min((abs(cur_cci) - 100) / 200 * 100, 100)
        elif cur_cci < -100:
            signal, reason = "BUY", f"CCI {cur_cci} — oversold"
            strength = (abs(cur_cci) - 100) / 100 * 100
        elif cur_cci > 200:
            signal, reason = "SELL", f"CCI {cur_cci} — extreme overbought"
            strength = min((cur_cci - 100) / 200 * 100, 100)
        elif cur_cci > 100:
            signal, reason = "SELL", f"CCI {cur_cci} — overbought"
            strength = (cur_cci - 100) / 100 * 100
        else:
            signal, reason = "NEUTRAL", f"CCI {cur_cci} — normal range"
            strength = 0
    else:
        signal, reason, strength = "NEUTRAL", "Insufficient data", 0

    return {
        "name": "CCI",
        "params": f"{period}",
        "values": {"cci": cur_cci},
        "levels": {"support": -100, "resistance": 100},
        "signal": signal,
        "strength": round(min(strength, 100), 1),
        "reason": reason,
        "series": {
            "cci": [_round(v, 2) for v in cci.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 12. Williams %R ────────────────────────────────────────────────────


def calc_williams_r(candles: list[dict], period: int = 14) -> dict:
    """Williams %R (14). Overbought >-20, Oversold <-80."""
    df = _build_df(candles)
    high, low, close = df["high"], df["low"], df["close"]

    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    wr = -100 * (hh - close) / (hh - ll)

    cur_wr = _round(wr.iloc[-1], 2)

    if cur_wr is not None:
        if cur_wr > -20:
            signal, reason = "SELL", f"%R {cur_wr} — overbought (near high)"
            strength = (cur_wr + 20) / 20 * 100
        elif cur_wr < -80:
            signal, reason = "BUY", f"%R {cur_wr} — oversold (near low)"
            strength = (-80 - cur_wr) / 20 * 100
        else:
            signal, reason = "NEUTRAL", f"%R {cur_wr} — normal range"
            strength = 0
    else:
        signal, reason, strength = "NEUTRAL", "Insufficient data", 0

    return {
        "name": "Williams %R",
        "params": f"{period}",
        "values": {"williams_r": cur_wr},
        "levels": {"support": -80, "resistance": -20},
        "signal": signal,
        "strength": round(min(strength, 100), 1),
        "reason": reason,
        "series": {
            "wr": [_round(v, 2) for v in wr.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 13. Parabolic SAR ─────────────────────────────────────────────────


def calc_parabolic_sar(candles: list[dict], af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2) -> dict:
    """Parabolic SAR. Support when uptrend, Resistance when downtrend."""
    df = _build_df(candles)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(close)

    sar = np.zeros(n)
    trend = np.ones(n)  # 1 = up, -1 = down
    ep = np.zeros(n)
    af = np.zeros(n)

    sar[0] = low[0]
    ep[0] = high[0]
    af[0] = af_start
    trend[0] = 1

    for i in range(1, n):
        prev_sar = sar[i - 1]
        prev_af = af[i - 1]
        prev_ep = ep[i - 1]
        prev_trend = trend[i - 1]

        sar[i] = prev_sar + prev_af * (prev_ep - prev_sar)

        if prev_trend == 1:
            sar[i] = min(sar[i], low[i - 1])
            if i >= 2:
                sar[i] = min(sar[i], low[i - 2])
            if low[i] < sar[i]:
                trend[i] = -1
                sar[i] = prev_ep
                ep[i] = low[i]
                af[i] = af_start
            else:
                trend[i] = 1
                if high[i] > prev_ep:
                    ep[i] = high[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af
        else:
            sar[i] = max(sar[i], high[i - 1])
            if i >= 2:
                sar[i] = max(sar[i], high[i - 2])
            if high[i] > sar[i]:
                trend[i] = 1
                sar[i] = prev_ep
                ep[i] = high[i]
                af[i] = af_start
            else:
                trend[i] = -1
                if low[i] < prev_ep:
                    ep[i] = low[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af

    cur_sar = _round(sar[-1], 4)
    cur_trend = "up" if trend[-1] == 1 else "down"
    cur_close = _round(close[-1], 4)

    # detect recent reversal (within last 3 bars)
    reversal = "none"
    for i in range(max(0, n - 3), n):
        if i > 0 and trend[i] != trend[i - 1]:
            reversal = "bullish" if trend[i] == 1 else "bearish"

    if cur_trend == "up":
        signal = "BUY"
        reason = f"SAR uptrend (SAR={cur_sar})"
        if reversal == "bullish":
            reason = "Fresh bullish reversal — SAR flipped below price"
            strength = 70
        else:
            strength = 40
    else:
        signal = "SELL"
        reason = f"SAR downtrend (SAR={cur_sar})"
        if reversal == "bearish":
            reason = "Fresh bearish reversal — SAR flipped above price"
            strength = 70
        else:
            strength = 40

    support = cur_sar if cur_trend == "up" else None
    resistance = cur_sar if cur_trend == "down" else None

    return {
        "name": "Parabolic SAR",
        "params": f"AF {af_start}/{af_step}/{af_max}",
        "values": {"sar": cur_sar, "trend": cur_trend, "reversal": reversal},
        "levels": {"support": support, "resistance": resistance},
        "signal": signal,
        "strength": round(strength, 1),
        "reason": reason,
        "series": {
            "sar": [_round(v, 4) for v in sar.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 14. MFI (Money Flow Index) ─────────────────────────────────────────


def calc_mfi(candles: list[dict], period: int = 14) -> dict:
    """MFI (14). Volume-weighted RSI. Overbought >80, Oversold <20."""
    df = _build_df(candles)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    direction = tp.diff()

    pos_mf = mf.where(direction > 0, 0.0)
    neg_mf = mf.where(direction < 0, 0.0)

    pos_sum = pos_mf.rolling(period).sum()
    neg_sum = neg_mf.rolling(period).sum()
    mfr = pos_sum / neg_sum
    mfi = 100 - 100 / (1 + mfr)

    cur_mfi = _round(mfi.iloc[-1], 2)

    if cur_mfi is not None:
        if cur_mfi < 20:
            signal, reason = "BUY", f"MFI {cur_mfi} — oversold (money outflow)"
            strength = (20 - cur_mfi) / 20 * 100
        elif cur_mfi > 80:
            signal, reason = "SELL", f"MFI {cur_mfi} — overbought (money inflow)"
            strength = (cur_mfi - 80) / 20 * 100
        else:
            signal, reason = "NEUTRAL", f"MFI {cur_mfi} — normal range"
            strength = 0
    else:
        signal, reason, strength = "NEUTRAL", "Insufficient data", 0

    return {
        "name": "MFI",
        "params": f"{period}",
        "values": {"mfi": cur_mfi},
        "levels": {"support": 20, "resistance": 80},
        "signal": signal,
        "strength": round(min(strength, 100), 1),
        "reason": reason,
        "series": {
            "mfi": [_round(v, 2) for v in mfi.tolist()],
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
    }


# ── 15. Fibonacci Retracements ─────────────────────────────────────────


def calc_fibonacci(candles: list[dict], lookback: int = 120) -> dict:
    """Fibonacci Retracements from recent swing high/low (last ~6 months)."""
    df = _build_df(candles)
    recent = df.tail(lookback)
    swing_high = float(recent["high"].max())
    swing_low = float(recent["low"].min())
    diff = swing_high - swing_low

    levels = {
        "0.0": _round(swing_low),
        "0.236": _round(swing_low + 0.236 * diff),
        "0.382": _round(swing_low + 0.382 * diff),
        "0.5": _round(swing_low + 0.5 * diff),
        "0.618": _round(swing_low + 0.618 * diff),
        "0.786": _round(swing_low + 0.786 * diff),
        "1.0": _round(swing_high),
    }

    cur_close = _round(df["close"].iloc[-1], 4)

    # find which fib level price is nearest
    fib_vals = list(levels.values())
    fib_keys = list(levels.keys())
    nearest_idx = min(range(len(fib_vals)), key=lambda i: abs(fib_vals[i] - cur_close) if fib_vals[i] else float('inf'))
    nearest_key = fib_keys[nearest_idx]
    nearest_val = fib_vals[nearest_idx]

    # signal based on position
    pct_from_low = (cur_close - swing_low) / diff * 100 if diff > 0 else 50
    if pct_from_low < 23.6:
        signal, reason = "BUY", f"Near 0% Fib (swing low zone) — strong support"
        strength = 80
    elif pct_from_low < 38.2:
        signal, reason = "BUY", f"Near 23.6% Fib — potential bounce"
        strength = 60
    elif pct_from_low > 78.6:
        signal, reason = "SELL", f"Near 100% Fib (swing high zone) — strong resistance"
        strength = 80
    elif pct_from_low > 61.8:
        signal, reason = "SELL", f"Near 61.8% Fib — potential rejection"
        strength = 60
    else:
        signal, reason = "NEUTRAL", f"At {nearest_key} Fib level ({nearest_val})"
        strength = 20

    return {
        "name": "Fibonacci",
        "params": f"{lookback}d swing",
        "values": {**levels, "nearest": nearest_key, "price_position_pct": round(pct_from_low, 1)},
        "levels": {"support": levels["0.236"], "resistance": levels["0.618"]},
        "signal": signal,
        "strength": round(strength, 1),
        "reason": reason,
        "series": {
            "dates": df["date"].dt.strftime("%Y-%m-%d").tolist(),
        },
        "fib_levels": levels,
    }


# ── Aggregate ───────────────────────────────────────────────────────────


def calc_all_indicators(candles: list[dict]) -> list[dict]:
    """Calculate all indicators and return a list of indicator dicts."""
    return [
        calc_macd(candles),
        calc_bollinger(candles),
        calc_ichimoku(candles),
        calc_demark(candles),
        calc_rsi(candles),
        calc_stochastic(candles),
        calc_adx(candles),
        calc_vwap(candles),
        calc_atr(candles),
        calc_obv(candles),
        calc_cci(candles),
        calc_williams_r(candles),
        calc_parabolic_sar(candles),
        calc_mfi(candles),
        calc_fibonacci(candles),
    ]


def calc_overall_signal(indicators: list[dict]) -> dict:
    """Aggregate all indicator signals into an overall recommendation."""
    score = 0
    total_weight = 0
    reasons = []

    weights = {
        "MACD": 2, "Bollinger Bands": 1.5, "Ichimoku": 2,
        "TD Sequential": 1.5, "RSI": 1, "CNN Fear & Greed": 1.5,
        "Stochastic": 1, "ADX": 1.5, "VWAP": 1, "ATR": 0.5,
        "OBV": 1, "CCI": 1, "Williams %R": 0.8, "Parabolic SAR": 1, "MFI": 1,
        "Fibonacci": 1.2,
    }

    for ind in indicators:
        w = weights.get(ind["name"], 1)
        s = ind["signal"]
        st = ind.get("strength", 0) / 100
        if s == "BUY":
            score += w * st
        elif s == "SELL":
            score -= w * st
        total_weight += w
        if s != "NEUTRAL":
            reasons.append(f'{ind["name"]}: {s}')

    if total_weight == 0:
        return {"signal": "NEUTRAL", "score": 0, "confidence": 0, "summary": "Insufficient data"}

    norm = score / total_weight * 100  # -100 to +100
    if norm > 20:
        overall = "BUY"
    elif norm < -20:
        overall = "SELL"
    else:
        overall = "NEUTRAL"

    confidence = min(abs(norm), 100)

    return {
        "signal": overall,
        "score": round(norm, 1),
        "confidence": round(confidence, 1),
        "summary": "; ".join(reasons) if reasons else "All indicators neutral",
    }
