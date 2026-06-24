"""LLM service — OpenAI-compatible API integration for stock analysis.

Stores config in data/llm_config.json.
Builds structured prompts from stock data + indicators.
Returns structured buy/sell/hold predictions.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from openai import OpenAI

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_config.json"

DEFAULT_CONFIG = {
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o",
    "temperature": 0.3,
    "max_tokens": 2000,
    "enabled": False,
}

SYSTEM_PROMPT = """You are a professional quantitative stock analyst. You will receive:
1. A stock's recent daily OHLCV candlestick data (last 30 trading days)
2. All computed technical indicators and their current signals
3. The current market sentiment (CNN Fear & Greed Index)
4. Recent news headlines about the company

Your task: Analyze all the data and predict the NEXT trading day's action.

You MUST respond with ONLY valid JSON (no markdown, no explanation outside JSON) in this exact format:
{
  "action": "BUY" | "SELL" | "HOLD",
  "buy_price": <number or null>,
  "sell_price": <number or null>,
  "stop_loss": <number>,
  "take_profit": <number>,
  "confidence": <0-100>,
  "timeframe": "1d",
  "reasoning": "<2-3 sentence summary of key factors>",
  "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
  "risk_reward": "<ratio like 1:2>",
  "news_impact": "<1-2 sentences on how recent news affects the prediction, or 'No significant news impact'>"
}

Rules:
- If action is BUY: set buy_price (limit order price, slightly below expected open), sell_price=null
- If action is SELL: set sell_price (limit order price, slightly above expected open), buy_price=null
- If action is HOLD: both buy_price and sell_price=null
- buy_price/sell_price should be realistic limit order prices based on recent volatility
- stop_loss should be based on ATR or key support/resistance levels
- take_profit should be based on next resistance/support level
- confidence should reflect the confluence (agreement) of indicators
- reasoning should reference specific indicator values
- risk_reward should reflect stop_loss vs take_profit distance
- news_impact should explain which news items (if any) influenced your decision and how"""


def get_config() -> dict:
    """Load LLM config from file, falling back to defaults."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            merged = {**DEFAULT_CONFIG, **saved}
            return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """Save LLM config to file."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


# ── Prompt version management ────────────────────────────────────────

PROMPTS_PATH = Path(__file__).resolve().parent.parent / "data" / "prompt_versions.json"


def get_prompt_versions() -> list[dict]:
    """Get all saved prompt versions."""
    if PROMPTS_PATH.exists():
        try:
            with open(PROMPTS_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    # return default as the only version
    return [{"id": "default", "name": "Default", "prompt": SYSTEM_PROMPT, "active": True, "created_at": "2025-01-01"}]


def save_prompt_version(name: str, prompt: str) -> dict:
    """Save a new prompt version."""
    versions = get_prompt_versions()
    # deactivate all
    for v in versions:
        v["active"] = False
    new_version = {
        "id": len(versions) + 1,
        "name": name,
        "prompt": prompt,
        "active": True,
        "created_at": datetime.now().isoformat()[:19],
    }
    versions.append(new_version)
    PROMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROMPTS_PATH, "w") as f:
        json.dump(versions, f, indent=2)
    return new_version


def set_active_prompt(version_id) -> dict:
    """Set a prompt version as active."""
    versions = get_prompt_versions()
    for v in versions:
        v["active"] = (v["id"] == version_id)
    PROMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROMPTS_PATH, "w") as f:
        json.dump(versions, f, indent=2)
    return {"active": version_id}


def get_active_prompt() -> str:
    """Get the currently active system prompt."""
    versions = get_prompt_versions()
    for v in versions:
        if v.get("active"):
            return v["prompt"]
    return SYSTEM_PROMPT


def _get_market_session() -> str:
    """Detect current market session based on US Eastern time."""
    from datetime import timezone, timedelta
    import pytz

    try:
        et = pytz.timezone("US/Eastern")
    except Exception:
        et = timezone(timedelta(hours=-4))

    now = datetime.now(et)
    hour = now.hour
    minute = now.minute
    weekday = now.weekday()  # 0=Mon, 6=Sun

    if weekday >= 5:
        return "closed_weekend"

    t = hour * 60 + minute
    if t < 240:  # before 4:00 AM
        return "closed_overnight"
    elif t < 570:  # 4:00 - 9:30 AM
        return "pre_market"
    elif t < 960:  # 9:30 AM - 4:00 PM
        return "regular"
    elif t < 1020:  # 4:00 - 5:00 PM
        return "after_hours"
    else:
        return "closed_after_hours"


def _get_session_context(session: str) -> str:
    """Get context text based on market session."""
    contexts = {
        "pre_market": "PRE-MARKET SESSION (4:00-9:30 AM ET). Use pre-market data and overnight news. Focus on OPENING strategy.",
        "regular": "MARKET IS OPEN (9:30 AM - 4:00 PM ET). Use real-time intraday data. Focus on INTRADAY trading decisions.",
        "after_hours": "AFTER-HOURS SESSION (4:00-5:00 PM ET). Use today's closing data. Focus on NEXT-DAY limit orders.",
        "closed_overnight": "MARKET CLOSED (overnight). Use today's closing data. Focus on NEXT-DAY limit orders.",
        "closed_weekend": "MARKET CLOSED (weekend). Use last trading day's data. Focus on MONDAY opening strategy.",
        "closed_after_hours": "MARKET CLOSED. Use today's closing data. Focus on NEXT-DAY limit orders.",
    }
    return contexts.get(session, "")


def _build_user_prompt(
    ticker: str, info: dict, candles: list[dict],
    indicators: list[dict], overall: dict, news_text: str = "", financials_text: str = "",
    session_context: str = "",
) -> str:
    """Build the analysis prompt from structured stock data."""

    # last 30 candles
    recent = candles[-30:]
    candle_lines = []
    for c in recent:
        candle_lines.append(
            f"  {c['date']}: O={c['open']} H={c['high']} L={c['low']} C={c['close']} V={c['volume']}"
        )

    # indicator summaries
    ind_blocks = []
    for ind in indicators:
        vals = ind.get("values", {})
        val_str = ", ".join(f"{k}={v}" for k, v in vals.items())
        levels = ind.get("levels", {})
        lvl_str = f"support={levels.get('support', 'N/A')}, resistance={levels.get('resistance', 'N/A')}"
        ind_blocks.append(
            f"  [{ind['name']}] signal={ind['signal']}, strength={ind['strength']}, "
            f"reason={ind.get('reason', 'N/A')}\n"
            f"    values: {val_str}\n"
            f"    levels: {lvl_str}"
        )

    news_block = f"\n\n--- Recent News ---\n{news_text}" if news_text else ""
    fin_block = f"\n\n{financials_text}" if financials_text else ""

    session_line = f"\n{session_context}\n" if session_context else ""

    return f"""Analyze {ticker} ({info.get('name', ticker)}).
{session_line}
Current price: {candles[-1]['close']} (as of {candles[-1]['date']})
Exchange: {info.get('exchange', 'N/A')}
Sector: {info.get('sector', 'N/A')}
Market Cap: {info.get('market_cap', 'N/A')}

--- Last 30 Daily Candles (OHLCV) ---
{chr(10).join(candle_lines)}

--- Technical Indicators ---
{chr(10).join(ind_blocks)}

--- Overall Signal ---
action={overall.get('signal', 'N/A')}, score={overall.get('score', 0)}, confidence={overall.get('confidence', 0)}
summary: {overall.get('summary', 'N/A')}
{news_block}{fin_block}

Based on all the above data, provide your next-day trading recommendation as JSON."""


def predict(ticker: str, info: dict, candles: list[dict], indicators: list[dict], overall: dict) -> dict:
    """Call LLM and return structured prediction."""
    from backend.financials_service import get_financials_for_llm
    from backend.news_service import get_news_for_llm

    config = get_config()

    if not config.get("enabled"):
        return {"error": "LLM is not enabled. Please configure it in Settings.", "enabled": False}

    if not config.get("api_key"):
        return {"error": "API key is not configured.", "enabled": False}

    client = OpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
    )

    # fetch news and financials for LLM context
    news_text = get_news_for_llm(ticker, limit=5)
    financials_text = get_financials_for_llm(ticker)

    # detect market session
    session = _get_market_session()
    session_context = _get_session_context(session)

    user_prompt = _build_user_prompt(ticker, info, candles, indicators, overall, news_text, financials_text, session_context)

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=config.get("temperature", 0.3),
            max_tokens=config.get("max_tokens", 2000),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content.strip()

        # strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

        result = json.loads(raw)
        result["enabled"] = True
        result["model"] = config["model"]
        result["raw_response"] = response.choices[0].message.content
        return result

    except json.JSONDecodeError:
        return {
            "error": "LLM returned invalid JSON",
            "raw_response": raw if 'raw' in dir() else "",
            "enabled": True,
        }
    except Exception as e:
        return {"error": str(e), "enabled": True}


# ── Multi-model presets ──────────────────────────────────────────────

MODEL_PRESETS = {
    "GPT-4o": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "GPT-4o Mini": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "Claude Sonnet": {"base_url": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-20250514"},
    "DeepSeek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "Qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "Ollama (local)": {"base_url": "http://localhost:11434/v1", "model": "llama3"},
}


# ── Anomaly detection ────────────────────────────────────────────────


def detect_anomaly(candles: list[dict], threshold_pct: float = 5.0) -> dict | None:
    """Detect if the latest candle is an anomaly (>threshold% move).

    Returns anomaly info or None if no anomaly detected.
    """
    if len(candles) < 2:
        return None

    latest = candles[-1]
    prev = candles[-2]

    change_pct = (latest["close"] - prev["close"]) / prev["close"] * 100
    volume_ratio = latest["volume"] / max(1, sum(c["volume"] for c in candles[-20:]) / 20) if len(candles) >= 20 else 1

    is_anomaly = abs(change_pct) >= threshold_pct or volume_ratio >= 3.0

    if not is_anomaly:
        return None

    return {
        "ticker": "",  # filled by caller
        "date": latest["date"],
        "close": latest["close"],
        "change_pct": round(change_pct, 2),
        "volume_ratio": round(volume_ratio, 2),
        "direction": "up" if change_pct > 0 else "down",
        "is_price_anomaly": abs(change_pct) >= threshold_pct,
        "is_volume_anomaly": volume_ratio >= 3.0,
    }


def bull_bear_debate(ticker: str, indicators: list[dict], overall: dict, current_price: float = None) -> dict:
    """Generate structured bull vs bear debate with arguments on both sides."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

    ind_summary = "\n".join(
        f"- {ind['name']}: {ind['signal']} (strength {ind['strength']}/100) — {ind.get('reason', '')}"
        for ind in indicators
    )

    prompt = f"""You are a debate moderator. Present both sides of the {ticker} trade (current price: ${current_price or 'N/A'}).

Technical indicators:
{ind_summary}

Overall signal: {overall.get('signal')} (score: {overall.get('score')})

Respond in JSON:
{{
  "bull_case": {{
    "thesis": "<1 sentence bull thesis>",
    "arguments": ["arg1", "arg2", "arg3"],
    "target_price": <number>,
    "probability": <0-100>
  }},
  "bear_case": {{
    "thesis": "<1 sentence bear thesis>",
    "arguments": ["arg1", "arg2", "arg3"],
    "target_price": <number>,
    "probability": <0-100>
  }},
  "verdict": "<which side is stronger and why, 1-2 sentences>",
  "key_catalyst": "<the one thing that could tip the balance>"
}}"""

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.4,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "LLM returned invalid JSON", "raw": raw}
    except Exception as e:
        return {"error": str(e)}


def analyze_news_impact(ticker: str, news_items: list[dict], holdings: list[dict] = None) -> dict:
    """Deep analysis of news impact on a stock and user's holdings."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

    news_text = "\n".join(
        f"- {n.get('title', '')} ({n.get('publisher', '')}, {n.get('published_at', '')[:10]})"
        for n in news_items[:10]
    )

    holdings_text = ""
    if holdings:
        holdings_text = "\nUser's holdings:\n" + "\n".join(
            f"- {h['ticker']}: {h.get('quantity', 0)} shares @ ${h.get('avg_cost', 0)}"
            for h in holdings
        )

    prompt = f"""Analyze these news headlines for {ticker} and explain their investment impact.
{holdings_text}

News:
{news_text}

Respond in JSON:
{{
  "overall_impact": "bullish" | "bearish" | "neutral",
  "impact_score": <-100 to 100>,
  "key_themes": ["theme1", "theme2"],
  "holdings_impact": "<how this affects user's portfolio, or 'N/A' if no holdings>",
  "action_suggestion": "<what the user should consider doing>",
  "one_line_summary": "<concise summary>"
}}"""

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.3,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "LLM returned invalid JSON", "raw": raw}
    except Exception as e:
        return {"error": str(e)}


def explain_anomaly(ticker: str, anomaly: dict, news_text: str = "") -> dict:
    """Use LLM to explain why a stock had an anomalous move."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

    direction = "surged" if anomaly["direction"] == "up" else "dropped"
    news_block = f"\nRecent news:\n{news_text}" if news_text else ""

    prompt = f"""{ticker} {direction} {abs(anomaly['change_pct'])}% on {anomaly['date']} (close: ${anomaly['close']}).
Volume was {anomaly['volume_ratio']}x the 20-day average.{news_block}

Explain in 2-3 sentences WHY this likely happened. Be specific and factual.
If news is available, reference it. If not, suggest possible reasons based on the price action."""

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.3,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"explanation": response.choices[0].message.content.strip()}
    except Exception as e:
        return {"error": str(e)}


def get_model_presets() -> dict:
    """Return available model presets."""
    return MODEL_PRESETS


# ── Multi-turn chat ──────────────────────────────────────────────────


def chat(db, ticker: str, user_message: str, context: dict) -> dict:
    """Multi-turn chat about a stock. Uses conversation history."""
    from backend.conversation_service import (
        build_messages_for_llm,
        get_history,
        save_message,
    )

    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured.", "enabled": False}

    # save user message
    save_message(db, ticker, "user", user_message)

    # build context-aware system prompt
    ctx_parts = [f"You are discussing {ticker} with the user."]
    if context.get("current_price"):
        ctx_parts.append(f"Current price: ${context['current_price']}")
    if context.get("last_prediction"):
        pred = context["last_prediction"]
        ctx_parts.append(f"Your last prediction: {pred.get('action')} with {pred.get('confidence')}% confidence.")
    if context.get("key_levels"):
        ctx_parts.append(f"Key levels: {context['key_levels']}")

    system = " ".join(ctx_parts) + "\nAnswer concisely in the same language as the user's question."

    # build messages with history
    history = get_history(db, ticker, limit=10)
    messages = [{"role": "system", "content": system}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=config.get("temperature", 0.5),
            max_tokens=1000,
            messages=messages,
        )
        reply = response.choices[0].message.content.strip()

        # save assistant reply
        save_message(db, ticker, "assistant", reply, model=config["model"])

        return {"reply": reply, "model": config["model"]}
    except Exception as e:
        return {"error": str(e)}


# ── Strategy explainer ────────────────────────────────────────────────


def ask_encyclopedia(question: str) -> dict:
    """Answer general investment questions — not tied to any stock."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

    system = """You are a friendly investment teacher for beginners. Explain concepts clearly using simple language and everyday analogies. Keep answers concise (2-4 paragraphs max). Use bullet points where helpful. If the user asks about a specific indicator, explain what it measures, how to read it, and what values are considered high/low. Respond in the same language as the user's question."""

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.5,
            max_tokens=800,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        )
        return {"answer": response.choices[0].message.content.strip()}
    except Exception as e:
        return {"error": str(e)}


def explain_indicator(indicator: dict, ticker: str, current_price: float = None) -> dict:
    """Use LLM to explain an indicator's current state in plain language."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

    vals = indicator.get("values", {})
    val_str = ", ".join(f"{k}={v}" for k, v in vals.items())
    levels = indicator.get("levels", {})

    prompt = f"""Explain this technical indicator to a stock market beginner in 2-3 simple sentences. Use plain language, avoid jargon.

Indicator: {indicator['name']} ({indicator.get('params', '')})
Ticker: {ticker}
Current Price: ${current_price or 'N/A'}
Signal: {indicator['signal']} (strength: {indicator['strength']}/100)
Reason: {indicator.get('reason', 'N/A')}
Values: {val_str}
Support: {levels.get('support', 'N/A')}, Resistance: {levels.get('resistance', 'N/A')}

Explain what this means for someone who has never traded stocks. Be concise and actionable."""

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.5,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"explanation": response.choices[0].message.content.strip()}
    except Exception as e:
        return {"error": str(e)}


# ── Bull/Bear comparison ─────────────────────────────────────────────


def assess_risk(candles: list[dict], indicators: list[dict], info: dict = None) -> dict:
    """Compute quantitative risk metrics from OHLCV data and indicators."""
    import numpy as np
    import pandas as pd

    df = pd.DataFrame(candles)
    close = df["close"]
    returns = close.pct_change().dropna()

    # volatility
    daily_vol = returns.std()
    annual_vol = daily_vol * np.sqrt(252)

    # max drawdown
    cummax = close.cummax()
    drawdown = (close - cummax) / cummax
    max_dd = drawdown.min()

    # beta (vs market proxy — use 0 as placeholder)
    # VaR (5%)
    var_5 = float(np.percentile(returns, 5))

    # Sharpe (assume 4.5% risk-free)
    rf_daily = 0.045 / 252
    sharpe = (returns.mean() - rf_daily) / daily_vol * np.sqrt(252) if daily_vol > 0 else 0

    # risk score 0-100 (higher = riskier)
    risk_score = 0
    if annual_vol > 0.5:
        risk_score += 30
    elif annual_vol > 0.3:
        risk_score += 20
    elif annual_vol > 0.2:
        risk_score += 10

    if max_dd < -0.4:
        risk_score += 30
    elif max_dd < -0.25:
        risk_score += 20
    elif max_dd < -0.15:
        risk_score += 10

    if var_5 < -0.05:
        risk_score += 20
    elif var_5 < -0.03:
        risk_score += 10

    risk_score = min(risk_score, 100)

    if risk_score >= 70:
        risk_level = "HIGH"
    elif risk_score >= 40:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "annual_volatility": round(float(annual_vol) * 100, 2),
        "max_drawdown": round(float(max_dd) * 100, 2),
        "daily_var_5pct": round(float(var_5) * 100, 2),
        "sharpe_ratio": round(float(sharpe), 2),
        "avg_daily_return": round(float(returns.mean()) * 100, 4),
        "positive_days_pct": round(float((returns > 0).mean()) * 100, 1),
    }


def get_dca_advice(ticker: str, indicators: list[dict], overall: dict, current_price: float = None) -> dict:
    """Generate DCA (Dollar Cost Averaging) advice based on valuation signals."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    # build indicator summary
    ind_text = "\n".join(
        f"- {ind['name']}: {ind['signal']} (strength {ind['strength']}/100) — {ind.get('reason', '')}"
        for ind in indicators
    )

    prompt = f"""You are a financial advisor for beginners. Based on the technical indicators below for {ticker} (current price: ${current_price or 'N/A'}),
provide DCA (Dollar Cost Averaging) advice.

Technical indicators:
{ind_text}

Overall signal: {overall.get('signal')} (score: {overall.get('score')})

Respond in JSON:
{{
  "recommendation": "INCREASE" | "MAINTAIN" | "DECREASE" | "PAUSE",
  "monthly_amount_suggestion": <number or null>,
  "reasoning": "<2-3 sentences explaining the recommendation>",
  "entry_strategy": "<1-2 sentences on how to enter (lump sum vs gradual)>",
  "risk_note": "<1 sentence about key risk>"
}}"""

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])
    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.4,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "LLM returned invalid JSON", "raw": raw}
    except Exception as e:
        return {"error": str(e)}


def get_chart_annotations(ticker: str, candles: list[dict], indicators: list[dict]) -> dict:
    """Generate chart annotations — key support/resistance levels from LLM analysis."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    # extract levels from indicators
    levels_text = []
    for ind in indicators:
        lvl = ind.get("levels", {})
        if lvl.get("support"):
            levels_text.append(f"{ind['name']} support: ${lvl['support']}")
        if lvl.get("resistance"):
            levels_text.append(f"{ind['name']} resistance: ${lvl['resistance']}")

    recent = candles[-10:]
    price_text = "\n".join(f"  {c['date']}: H={c['high']} L={c['low']} C={c['close']}" for c in recent)

    prompt = f"""Based on the recent price action and indicator levels for {ticker}, identify the 3 most important support levels and 3 most important resistance levels for the NEXT trading day.

Recent prices:
{price_text}

Indicator levels:
{chr(10).join(levels_text)}

Respond in JSON:
{{
  "support_levels": [{{"price": <number>, "strength": "strong"|"moderate"|"weak", "source": "<what indicator/price action>"}}, ...],
  "resistance_levels": [{{"price": <number>, "strength": "strong"|"moderate"|"weak", "source": "<what indicator/price action>"}}, ...],
  "trend_line": {{"slope": "up"|"down"|"flat", "description": "<brief description>"}}
}}"""

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])
    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.3,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "LLM returned invalid JSON", "raw": raw}
    except Exception as e:
        return {"error": str(e)}


def get_learning_path(user_level: str = "beginner", interests: list[str] = None) -> dict:
    """Recommend a learning path based on user level and interests."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    interest_text = ", ".join(interests) if interests else "general investing"
    prompt = f"""Create a learning path for a {user_level} investor interested in {interest_text}.

Respond in JSON:
{{
  "level": "{user_level}",
  "topics": [
    {{"title": "<topic>", "description": "<1-2 sentences>", "difficulty": "beginner|intermediate|advanced", "key_concepts": ["<concept1>", "<concept2>"]}},
    ...
  ],
  "suggested_order": ["<topic1>", "<topic2>", ...],
  "estimated_hours": <number>
}}

Provide 5-8 topics, ordered from foundational to advanced."""

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])
    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.5,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "LLM returned invalid JSON", "raw": raw}
    except Exception as e:
        return {"error": str(e)}


def bull_bear_analysis(ticker: str, indicators: list[dict], overall: dict, current_price: float = None) -> dict:
    """Generate both bull and bear cases — let the user decide."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

    # build indicator summary
    ind_summary = []
    for ind in indicators:
        ind_summary.append(f"- {ind['name']}: signal={ind['signal']}, reason={ind.get('reason','')}")
    ind_text = "\n".join(ind_summary)

    prompt = f"""Analyze {ticker} (current price: ${current_price or 'N/A'}) and provide BOTH a bull case and a bear case.

Technical indicators:
{ind_text}

Overall signal: {overall.get('signal')} (score: {overall.get('score')})

Respond in this exact JSON format:
{{
  "bull_case": {{
    "summary": "2-3 sentences on why this stock could go UP",
    "target_price": <number>,
    "key_drives": ["reason1", "reason2"],
    "probability": <0-100>
  }},
  "bear_case": {{
    "summary": "2-3 sentences on why this stock could go DOWN",
    "target_price": <number>,
    "key_risks": ["risk1", "risk2"],
    "probability": <0-100>
  }}
}}"""

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.4,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        # strip markdown
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "LLM returned invalid JSON", "raw": raw}
    except Exception as e:
        return {"error": str(e)}


# ── Structured report ────────────────────────────────────────────────


def generate_report(ticker: str, info: dict, indicators: list[dict], overall: dict, prediction: dict = None) -> dict:
    """Generate a Markdown analysis report."""
    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        return {"error": "LLM is not configured."}

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])

    pred_text = ""
    if prediction and not prediction.get("error"):
        pred_text = f"""
Latest LLM Prediction:
- Action: {prediction.get('action')}
- Buy Price: ${prediction.get('buy_price', 'N/A')}
- Sell Price: ${prediction.get('sell_price', 'N/A')}
- Stop Loss: ${prediction.get('stop_loss', 'N/A')}
- Take Profit: ${prediction.get('take_profit', 'N/A')}
- Confidence: {prediction.get('confidence', 'N/A')}%
- Reasoning: {prediction.get('reasoning', 'N/A')}
"""

    ind_lines = []
    for ind in indicators:
        ind_lines.append(f"| {ind['name']} | {ind['signal']} | {ind['strength']}/100 | {ind.get('reason', '')} |")
    ind_table = "\n".join(ind_lines)

    prompt = f"""Generate a professional stock analysis report in Markdown for {ticker} ({info.get('name', '')}).

Company: {info.get('name', '')} | Exchange: {info.get('exchange', 'N/A')} | Sector: {info.get('sector', 'N/A')}
Overall Signal: {overall.get('signal')} (score: {overall.get('score')}, confidence: {overall.get('confidence')}%)

Technical Indicators:
| Indicator | Signal | Strength | Reason |
|-----------|--------|----------|--------|
{ind_table}
{pred_text}
Write a clean, professional Markdown report with these sections:
# {ticker} Analysis Report
## Executive Summary
## Technical Analysis
## Key Indicators
## Risk Assessment
## Recommendation

Keep it concise (under 500 words). Use bullet points. Be professional but accessible."""

    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.3,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"report": response.choices[0].message.content.strip(), "format": "markdown"}
    except Exception as e:
        return {"error": str(e)}
