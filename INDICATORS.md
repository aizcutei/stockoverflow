# Technical Indicators — Formulas & Signal Logic

## 1. MACD (12/26/9)
**Formula:**
- MACD Line = EMA(12) - EMA(26)
- Signal Line = EMA(9) of MACD Line
- Histogram = MACD Line - Signal Line

**Signal:**
- BUY: MACD crosses above Signal (bullish crossover) or MACD > Signal
- SELL: MACD crosses below Signal (bearish crossover) or MACD < Signal

**Support/Resistance:** Recent histogram high/low

## 2. Bollinger Bands (20/2σ)
**Formula:**
- Middle = SMA(20)
- Upper = Middle + 2 × StdDev(20)
- Lower = Middle - 2 × StdDev(20)
- %B = (Price - Lower) / (Upper - Lower)

**Signal:**
- BUY: %B < 0.05 (price at lower band — oversold)
- SELL: %B > 0.95 (price at upper band — overbought)
- WATCH: Bandwidth squeeze (breakout imminent)

## 3. Ichimoku Cloud (9/26/52/26)
**Formula:**
- Tenkan-sen = (Highest High(9) + Lowest Low(9)) / 2
- Kijun-sen = (Highest High(26) + Lowest Low(26)) / 2
- Senkou A = (Tenkan + Kijun) / 2, shifted 26 forward
- Senkou B = (Highest High(52) + Lowest Low(52)) / 2, shifted 26 forward

**Signal:**
- BUY: Price above cloud + Tenkan > Kijun
- SELL: Price below cloud + Tenkan < Kijun

**Support/Resistance:** Cloud top/bottom

## 4. TD Sequential (9/13)
**Formula:**
- Setup: Count consecutive bars where Close < Close[4] (buy) or Close > Close[4] (sell)
- After 9-count setup, start countdown to 13

**Signal:**
- BUY: 9 buy setup completed or 13 buy countdown
- SELL: 9 sell setup completed or 13 sell countdown

## 5. RSI (14)
**Formula:**
- Gain = max(0, Close - Close[-1])
- Loss = max(0, Close[-1] - Close)
- Avg Gain = EMA(14) of Gain
- Avg Loss = EMA(14) of Loss
- RS = Avg Gain / Avg Loss
- RSI = 100 - 100 / (1 + RS)

**Signal:**
- BUY: RSI < 30 (oversold)
- SELL: RSI > 70 (overbought)

## 6. Stochastic %K/%D (14/3/3)
**Formula:**
- %K = 100 × (Close - Lowest Low(14)) / (Highest High(14) - Lowest Low(14))
- %D = SMA(3) of %K

**Signal:**
- BUY: %K < 20 (oversold zone)
- SELL: %K > 80 (overbought zone)

## 7. ADX (14)
**Formula:**
- +DM = max(0, High - High[-1])
- -DM = max(0, Low[-1] - Low)
- TR = max(High-Low, |High-Close[-1]|, |Low-Close[-1]|)
- +DI = 100 × EMA(+DM) / EMA(TR)
- -DI = 100 × EMA(-DM) / EMA(TR)
- DX = 100 × |+DI - -DI| / (+DI + -DI)
- ADX = EMA(DX)

**Signal:**
- BUY: ADX > 25 and +DI > -DI (strong uptrend)
- SELL: ADX > 25 and -DI > +DI (strong downtrend)

## 8. VWAP
**Formula:**
- VWAP = Cumulative(Price × Volume) / Cumulative(Volume)

**Signal:**
- BUY: Price < VWAP × 0.98 (deep discount)
- SELL: Price > VWAP × 1.02 (extended)

## 9. ATR (14)
**Formula:**
- TR = max(High-Low, |High-Close[-1]|, |Low-Close[-1]|)
- ATR = EMA(14) of TR

**Signal:** Not directional — measures volatility for stop-loss sizing

## 10. OBV (On-Balance Volume)
**Formula:**
- If Close > Close[-1]: OBV += Volume
- If Close < Close[-1]: OBV -= Volume

**Signal:**
- BUY: Bullish divergence (price down, OBV up)
- SELL: Bearish divergence (price up, OBV down)

## 11. CCI (20)
**Formula:**
- TP = (High + Low + Close) / 3
- CCI = (TP - SMA(20)) / (0.015 × Mean Absolute Deviation)

**Signal:**
- BUY: CCI < -100 (oversold)
- SELL: CCI > 100 (overbought)

## 12. Williams %R (14)
**Formula:**
- %R = -100 × (Highest High(14) - Close) / (Highest High(14) - Lowest Low(14))

**Signal:**
- BUY: %R < -80 (oversold)
- SELL: %R > -20 (overbought)

## 13. Parabolic SAR
**Formula:**
- SAR = SAR[-1] + AF × (EP - SAR[-1])
- AF starts at 0.02, increases by 0.02 each bar, max 0.2
- EP = extreme point (highest high or lowest low)

**Signal:**
- BUY: SAR flips below price (bullish reversal)
- SELL: SAR flips above price (bearish reversal)

## 14. MFI (14)
**Formula:**
- TP = (High + Low + Close) / 3
- MF = TP × Volume
- Positive MF = MF where TP > TP[-1]
- Negative MF = MF where TP < TP[-1]
- MFR = Sum(Positive MF) / Sum(Negative MF)
- MFI = 100 - 100 / (1 + MFR)

**Signal:**
- BUY: MFI < 20 (money outflow, oversold)
- SELL: MFI > 80 (money inflow, overbought)

## 15. Fibonacci Retracements
**Formula:**
- Swing High/Low from recent 120 days
- Levels: 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%

**Signal:**
- BUY: Price near 23.6% (swing low zone)
- SELL: Price near 61.8% (swing high zone)

## 16. CNN Fear & Greed Index
**Source:** CNN API (market-wide sentiment, 0-100)

**Sub-indicators:**
- S&P 500 Momentum
- Stock Price Strength
- Stock Price Breadth
- Put/Call Options
- VIX Volatility
- Junk Bond Demand
- Safe Haven Demand

**Signal (contrarian):**
- BUY: Extreme Fear (score < 25)
- SELL: Extreme Greed (score > 75)
