"""
Layer 3 — Portfolio Monitoring
TIGER S&P 500 ETF + news. Real Yahoo Finance call when available;
realistic synthetic data for demo when not.
"""

import json
import os
import random
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from database import get_connection


# ─── PRICE DATA ────────────────────────────────────────────────────

def _try_yahoo_finance(ticker: str) -> dict | None:
    """
    Try Yahoo Finance API (no key needed). Returns None on any failure.
    Korean ETFs use suffix `.KS` (KOSPI) — TIGER S&P500 is 360750.KS.
    """
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range=1mo&interval=1d")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (FinancialOS demo)"
        })
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
        result = data["chart"]["result"][0]
        meta = result["meta"]
        timestamps = result.get("timestamp", [])
        closes = result["indicators"]["quote"][0].get("close", [])
        history = [
            {"date": datetime.fromtimestamp(t).date().isoformat(), "price": c}
            for t, c in zip(timestamps, closes) if c is not None
        ]
        return {
            "ticker": ticker,
            "current": meta["regularMarketPrice"],
            "previous_close": meta["chartPreviousClose"],
            "currency": meta.get("currency", "KRW"),
            "history": history,
            "source": "yahoo",
        }
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def _synthetic_price(holding: dict) -> dict:
    """
    Generate realistic synthetic price data when Yahoo is unreachable.
    Uses cost basis as anchor and produces a believable 30-day walk.
    """
    seed = int(holding.get("ticker", "0").replace(".KS", "0").replace(".", ""))
    rng = random.Random(seed + datetime.now().toordinal())
    cost = holding["cost_basis"]
    today_price = cost * (1.0 + rng.uniform(0.05, 0.15))  # +5–15% over cost
    prev = today_price * (1.0 + rng.uniform(-0.012, 0.012))

    history = []
    p = today_price * 0.93
    for i in range(30):
        d = (datetime.now() - timedelta(days=29 - i)).date()
        # gentle uptrend with noise
        p = p * (1.0 + rng.uniform(-0.018, 0.022))
        history.append({"date": d.isoformat(), "price": round(p, 2)})
    history[-1]["price"] = round(today_price, 2)

    return {
        "ticker": holding["ticker"],
        "current": round(today_price, 2),
        "previous_close": round(prev, 2),
        "currency": "KRW",
        "history": history,
        "source": "synthetic",
    }


def get_portfolio_snapshot() -> dict:
    conn = get_connection()
    try:
        holdings = [dict(r) for r in conn.execute(
            "SELECT * FROM portfolio_holdings"
        ).fetchall()]
    finally:
        conn.close()

    enriched = []
    total_value = 0
    total_cost = 0
    daily_change = 0

    for h in holdings:
        price_data = _try_yahoo_finance(h["ticker"]) or _synthetic_price(h)

        current = price_data["current"]
        prev = price_data["previous_close"]
        market_value = current * h["quantity"]
        cost_value = h["cost_basis"] * h["quantity"]
        day_change = (current - prev) * h["quantity"]
        total_return = market_value - cost_value
        total_return_pct = (total_return / cost_value * 100) if cost_value else 0
        day_change_pct = ((current - prev) / prev * 100) if prev else 0

        enriched.append({
            "ticker": h["ticker"],
            "name": h["name"],
            "quantity": h["quantity"],
            "cost_basis": h["cost_basis"],
            "current_price": current,
            "market_value": round(market_value),
            "cost_value": round(cost_value),
            "total_return": round(total_return),
            "total_return_pct": round(total_return_pct, 2),
            "day_change": round(day_change),
            "day_change_pct": round(day_change_pct, 2),
            "history": price_data["history"],
            "source": price_data["source"],
        })

        total_value += market_value
        total_cost += cost_value
        daily_change += day_change

        # Update DB current_price
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE portfolio_holdings SET current_price = ?,
                   last_updated = CURRENT_TIMESTAMP WHERE ticker = ?""",
                (current, h["ticker"])
            )
            for point in price_data["history"]:
                conn.execute(
                    """INSERT OR IGNORE INTO price_history (ticker, price, captured)
                       VALUES (?, ?, ?)""",
                    (h["ticker"], point["price"], point["date"])
                )
            conn.commit()
        finally:
            conn.close()

    return {
        "holdings": enriched,
        "total_market_value": round(total_value),
        "total_cost_basis": round(total_cost),
        "total_return": round(total_value - total_cost),
        "total_return_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0,
        "daily_change": round(daily_change),
        "daily_change_pct": round(daily_change / (total_value - daily_change) * 100, 2) if total_value else 0,
    }


# ─── NEWS ──────────────────────────────────────────────────────────

_SYNTHETIC_NEWS = [
    {
        "title": "S&P 500 closes at fresh record high as tech stocks rally",
        "source": "Reuters", "url": "#",
        "published": "2h ago",
        "snippet": "The benchmark gained 0.8% in afternoon trading, led by semiconductor names...",
    },
    {
        "title": "Korean retail investors increased S&P 500 ETF holdings in April",
        "source": "Korea Herald", "url": "#",
        "published": "4h ago",
        "snippet": "TIGER S&P 500 saw net inflows of 280 billion won last month...",
    },
    {
        "title": "Fed minutes show committee leaning hawkish on cut timeline",
        "source": "Bloomberg", "url": "#",
        "published": "8h ago",
        "snippet": "Officials remain divided on the pace of any easing this year...",
    },
    {
        "title": "Won weakens past 1,380 on dollar; impact on USD-denominated ETFs",
        "source": "Yonhap", "url": "#",
        "published": "12h ago",
        "snippet": "The won fell against the dollar amid rate differential concerns...",
    },
    {
        "title": "Samsung earnings beat lifts KOSPI; tech sector outlook brightens",
        "source": "Maeil Business", "url": "#",
        "published": "1d ago",
        "snippet": "Strong memory chip demand drove Q1 results above consensus...",
    },
]


def get_news(keywords: str = "S&P 500", hours: int = 24) -> list[dict]:
    """
    Fetch news. Tries NewsData.io if key present, else returns curated synthetic.
    """
    api_key = os.getenv("NEWSDATA_API_KEY")
    if api_key:
        try:
            url = (f"https://newsdata.io/api/1/news?apikey={api_key}"
                   f"&q={urllib.parse.quote(keywords)}&language=en,ko&size=5")
            with urllib.request.urlopen(url, timeout=4) as resp:
                data = json.loads(resp.read().decode())
            return [
                {
                    "title": a["title"],
                    "source": a.get("source_id", "unknown"),
                    "url": a.get("link", "#"),
                    "published": a.get("pubDate", ""),
                    "snippet": (a.get("description", "") or "")[:200],
                }
                for a in data.get("results", [])[:5]
            ]
        except Exception:
            pass
    return _SYNTHETIC_NEWS
