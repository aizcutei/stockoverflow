# StockOverflow — User Guide

## Quick Start

```bash
uv sync              # Install dependencies
uv run python main.py  # Start server
```

Open http://127.0.0.1:8000

## Features Overview

### 🔍 Stock Search
- Type a ticker (e.g. `AAPL`) or company name (e.g. `Tesla`) in the search bar
- Press Enter or click a result to load the stock
- Data is cached locally — subsequent loads are instant

### 📊 Charts
- **Candlestick chart** with volume bars below
- **Fullscreen mode**: press `f` or click ⛶
- **Theme toggle**: press `t` or click 🌙/☀️
- **Share**: click 🔗 to copy the stock URL

### 📈 Technical Indicators (16)
Each indicator has an **Overlay** toggle to draw it on the chart:

| Indicator | Type | Overlay |
|---|---|---|
| MACD (12/26/9) | Momentum | Sub-chart |
| Bollinger Bands (20/2σ) | Volatility | Price overlay |
| Ichimoku (9/26/52/26) | Trend | Price overlay |
| TD Sequential (9/13) | Exhaustion | Markers |
| RSI (14) | Momentum | Sub-chart |
| Stochastic (14/3/3) | Momentum | Sub-chart |
| ADX (14) | Trend Strength | Sub-chart |
| VWAP | Price/Volume | Price overlay |
| ATR (14) | Volatility | Sub-chart |
| OBV | Volume | Sub-chart |
| CCI (20) | Momentum | Sub-chart |
| Williams %R (14) | Momentum | Sub-chart |
| Parabolic SAR | Trend | Price overlay |
| MFI (14) | Volume | Sub-chart |
| Fibonacci (120d) | Support/Resistance | Price overlay |
| CNN Fear & Greed | Sentiment | Sub-chart |

### 🧪 Factor Lab
Write custom factor expressions and evaluate them:

```
rsi(14) < 30
macd_cross('bullish') and volume > sma(volume, 20)
close > bb_upper(20, 2) and adx(14) > 25
```

Available functions: `rsi()`, `macd_cross()`, `bb_upper()`, `bb_lower()`, `adx()`, `atr()`, `stochastic_k()`, `cci()`, `williams_r()`, `mfi()`, `vwap()`, `returns()`, `volatility()`, `volume_ratio()`, `sma()`, `ema()`, `obv()`

Features:
- **Evaluate**: see current value and signal
- **Save**: save custom factors to your library
- **Backtest**: run buy/sell strategies with equity curve
- **Compare**: compare multiple strategies side-by-side
- **Sensitivity**: grid search optimal parameters
- **Distribution**: histogram of factor values
- **Quintile**: split into 5 groups, compare returns
- **IC Analysis**: predictive power at various lags
- **Decay**: how factor power fades over time
- **Multi-Factor**: weighted combination of factors
- **Orthogonalize**: remove multicollinearity
- **Neutralize**: remove trend/mean exposure
- **Correlation**: heatmap between factors

### 🤖 LLM Predictions
Click **🔮 Predict** to get AI-powered next-day trading advice:
- Configure your LLM in ⚙️ Settings (OpenAI, Claude, DeepSeek, Qwen, Ollama)
- Prediction includes: action, buy/sell price, stop loss, take profit, confidence
- **Chat**: ask follow-up questions about the stock
- **DCA advice**: get dollar-cost averaging recommendations
- **Chart annotations**: LLM marks key support/resistance levels

### 💰 Paper Trading
- **Buy/Sell**: place market orders at current price
- **Limit/Stop orders**: set trigger prices for auto-execution
- **Watchlist**: ⭐ button to save favorite stocks
- **Dashboard**: see account, positions, recent trades

### ⌨️ Keyboard Shortcuts
| Key | Action |
|---|---|
| `/` | Focus search bar |
| `t` | Toggle theme (dark/light) |
| `s` | Open settings |
| `d` | Go to dashboard |
| `p` | Run LLM prediction |
| `f` | Toggle fullscreen chart |
| `Esc` | Close modals/clear search |

## Docker Deployment

```bash
docker build -t stockoverflow .
docker run -p 8000:8000 -v ./data:/app/data stockoverflow
```

Or with docker-compose:
```bash
docker-compose up -d
```

## Environment Variables

Copy `.env.example` to `.env` and configure:
- `DEFAULT_HISTORY_PERIOD` — how much data to fetch (1y/2y/5y/max)
- `LLM_BASE_URL` — OpenAI-compatible API endpoint
- `LLM_API_KEY` — your API key
- `LLM_MODEL` — model name
