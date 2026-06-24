"""Stock news service — multi-source (yfinance + Finviz), cache in memory."""

from __future__ import annotations

import json
import re
import time

import httpx
import yfinance as yf

# in-memory cache: { ticker: { "data": [...], "ts": epoch } }
_cache: dict[str, dict] = {}
CACHE_TTL = 3600  # 1 hour

FINVIZ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


def _fetch_finviz_news(ticker: str, limit: int = 10) -> list[dict]:
    """Fetch news from Finviz as a secondary source."""
    try:
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        resp = httpx.get(url, headers=FINVIZ_HEADERS, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return []

        # parse news table from HTML
        html = resp.text
        news_items = []
        # find news links in the page
        pattern = r'<a[^>]+class="tab-link-news"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)

        for link, title in matches[:limit]:
            news_items.append({
                "title": title.strip(),
                "summary": "",
                "url": link,
                "publisher": "Finviz",
                "published_at": "",
                "thumbnail": None,
                "source": "finviz",
            })

        return news_items
    except Exception:
        return []


def fetch_news(ticker: str, limit: int = 10, sources: str = "all") -> list[dict]:
    """Fetch news from multiple sources (yfinance + Finviz)."""
    ticker = ticker.upper().strip()

    # serve from cache if fresh
    cached = _cache.get(ticker)
    if cached and (time.time() - cached["ts"]) < CACHE_TTL:
        return cached["data"][:limit]

    items = []
    seen_titles = set()

    # source 1: yfinance
    if sources in ("all", "yfinance"):
        try:
            tk = yf.Ticker(ticker)
            raw_news = tk.news or []
            for item in raw_news[:limit * 2]:
                content = item.get("content", {})
                if not content:
                    continue
                title = content.get("title", "")
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)

                thumbnail = None
                if content.get("thumbnail"):
                    resolutions = content["thumbnail"].get("resolutions", [])
                    if resolutions:
                        thumbnail = resolutions[0].get("url")

                items.append({
                    "title": title,
                    "summary": content.get("summary", ""),
                    "url": content.get("canonicalUrl", {}).get("url", ""),
                    "publisher": content.get("provider", {}).get("displayName", ""),
                    "published_at": content.get("pubDate", ""),
                    "thumbnail": thumbnail,
                    "source": "yfinance",
                })
        except Exception:
            pass

    # source 2: Finviz
    if sources in ("all", "finviz"):
        finviz_items = _fetch_finviz_news(ticker, limit)
        for item in finviz_items:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                items.append(item)

    # fallback to cache if no results
    if not items and cached:
        return cached["data"][:limit]

    _cache[ticker] = {"data": items, "ts": time.time()}
    return items[:limit]


def analyze_news_sentiment(ticker: str, limit: int = 5) -> list[dict]:
    """Analyze sentiment for each news headline using LLM."""
    from backend.llm_service import get_config
    from openai import OpenAI

    news = fetch_news(ticker, limit)
    if not news:
        return []

    config = get_config()
    if not config.get("enabled") or not config.get("api_key"):
        # return news without sentiment
        return [{**n, "sentiment": None} for n in news]

    headlines = [n.get("title", "") for n in news]
    prompt = f"""For each news headline below, classify sentiment as BULLISH, BEARISH, or NEUTRAL,
AND extract 1-3 keywords that are most relevant to the stock's price movement.

Respond with ONLY a JSON array of objects, one per headline:
[{{"sentiment":"BULLISH","keywords":["iPhone","revenue"]}}, ...]

Headlines:
{chr(10).join(f'{i+1}. {h}' for i, h in enumerate(headlines))}"""

    client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])
    try:
        response = client.chat.completions.create(
            model=config["model"],
            temperature=0.1,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        parsed = json.loads(raw)
    except Exception:
        parsed = [None] * len(news)

    result = []
    for i, n in enumerate(news):
        if i < len(parsed) and isinstance(parsed[i], dict):
            s = parsed[i].get("sentiment", "")
            kw = parsed[i].get("keywords", [])
        elif i < len(parsed) and isinstance(parsed[i], str):
            s = parsed[i]
            kw = []
        else:
            s, kw = None, []

        if isinstance(s, str):
            s = s.upper().strip()
            if s not in ("BULLISH", "BEARISH", "NEUTRAL"):
                s = None

        result.append({**n, "sentiment": s, "keywords": kw})
    return result


def get_news_for_llm(ticker: str, limit: int = 5) -> str:
    """Get news as formatted text for LLM context."""
    news = fetch_news(ticker, limit)
    if not news:
        return "No recent news available."

    lines = []
    for i, item in enumerate(news, 1):
        title = item.get("title", "Untitled")
        summary = item.get("summary", "")
        pub = item.get("publisher", "")
        date = item.get("published_at", "")[:10]  # just date part
        lines.append(f"{i}. [{pub}] {title} ({date})")
        if summary:
            lines.append(f"   {summary[:200]}")
    return "\n".join(lines)
