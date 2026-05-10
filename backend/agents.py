"""
Layer 4 & 5 — Research Agent and Investment Committee
Real Claude API calls when ANTHROPIC_API_KEY is set; canned responses otherwise.
"""

import json
import os
import re
from datetime import datetime
from typing import Iterator
from database import get_connection
from portfolio_service import get_portfolio_snapshot, get_news
from spending_service import get_spending_summary, get_reimbursements_outstanding

# Try to import anthropic; gracefully degrade if not installed
try:
    import anthropic
    _CLAUDE_AVAILABLE = True
except ImportError:
    _CLAUDE_AVAILABLE = False


CLAUDE_MODEL = "claude-opus-4-7"


def _has_api_key() -> bool:
    return _CLAUDE_AVAILABLE and bool(os.getenv("ANTHROPIC_API_KEY"))


def _client():
    return anthropic.Anthropic()


# ─── CONTEXT BUILDERS ──────────────────────────────────────────────

def _build_context(query: str) -> dict:
    """Pull all the context the agents need."""
    portfolio = get_portfolio_snapshot()
    spending = get_spending_summary("month")
    reimbursements = get_reimbursements_outstanding()
    news = get_news("S&P 500 OR semiconductor OR Federal Reserve", hours=24)
    return {
        "query": query,
        "now": datetime.now().isoformat(),
        "portfolio": portfolio,
        "spending": spending,
        "reimbursements": reimbursements,
        "news": news,
    }


def _format_context_brief(ctx: dict) -> str:
    """Compact text summary of context for prompts."""
    p = ctx["portfolio"]
    s = ctx["spending"]
    h = p["holdings"][0] if p["holdings"] else {}

    cards_summary = []
    for cid, c in s["per_card"].items():
        if c["budget_max"]:
            cards_summary.append(f"Card {cid}: ₩{c['spent']:,} / ₩{c['budget_max']:,} ({c['pct_used']}%)")
        else:
            cards_summary.append(f"Card {cid}: ₩{c['spent']:,}")

    reimb_total = sum(r["owes"] for r in ctx["reimbursements"])

    return f"""CURRENT POSITION:
- {h.get('name', 'N/A')}: {h.get('quantity', 0)} shares
- Cost basis: ₩{h.get('cost_basis', 0):,}/share | Current: ₩{h.get('current_price', 0):,}/share
- Market value: ₩{h.get('market_value', 0):,} | Return: {h.get('total_return_pct', 0)}%
- 30-day low: ₩{min(pt['price'] for pt in h.get('history', [{'price':0}])):,.0f}
- 30-day high: ₩{max(pt['price'] for pt in h.get('history', [{'price':0}])):,.0f}

THIS MONTH'S SPENDING:
- {' | '.join(cards_summary)}
- Days remaining in month: {s['days_remaining_in_month']}
- Outstanding reimbursements: ₩{reimb_total:,}

RECENT HEADLINES:
{chr(10).join(f"- {n['title']} ({n['source']})" for n in ctx['news'][:3])}
"""


# ─── RESEARCH AGENT ────────────────────────────────────────────────

RESEARCH_SYSTEM = """You are a careful, evidence-based research analyst writing a memo for a 23-year-old Korean retail investor (university student) holding a Korean S&P 500 ETF.

Style:
- Write in clear English. Cite specific numbers from the context.
- Acknowledge uncertainty. Avoid hype or fear language.
- Output structured markdown with these sections:
  ## Question
  ## Key Data
  ## Analysis (3 short paragraphs)
  ## Recommendation (one direct sentence + position-sizing rationale)
- Date the memo at the top.
- Maximum 350 words total."""


def _canned_research_memo(query: str, ctx: dict) -> str:
    """Demo-grade memo when no API key — still uses real numbers."""
    p = ctx["portfolio"]["holdings"][0] if ctx["portfolio"]["holdings"] else {}
    s = ctx["spending"]
    cash_pressure = "elevated" if any(c["pct_used"] and c["pct_used"] > 70 for c in s["per_card"].values()) else "manageable"
    return f"""# Research Memo
**Date**: {datetime.now().strftime('%Y-%m-%d')}

## Question
{query}

## Key Data
- TIGER S&P 500 current: ₩{p.get('current_price', 0):,.0f}/share
- 30-day range: ₩{min(pt['price'] for pt in p.get('history',[{'price':0}])):,.0f}–₩{max(pt['price'] for pt in p.get('history',[{'price':0}])):,.0f}
- Position return so far: {p.get('total_return_pct', 0)}%
- Daily move: {p.get('day_change_pct', 0)}%

## Analysis

The position is up {p.get('total_return_pct', 0)}% from cost, well within a normal hold-and-add range for a passive index ETF strategy. The 30-day price action shows the typical small-amplitude noise that comes with broad-market exposure rather than a meaningful trend break either way.

Macro context this week leans neutral: rate-cut timing remains the swing factor, with FOMC minutes leaning slightly hawkish. For a long-horizon DCA strategy, this is largely noise. Won-dollar weakness is a tailwind for KRW-denominated S&P 500 ETFs.

Personal cash situation is {cash_pressure} — Card B utilization is {next(iter([c['pct_used'] for c in s['per_card'].values() if c['pct_used']]), 0)}% with {s['days_remaining_in_month']} days left in the month. Adding to the position should not strain end-of-month liquidity.

## Recommendation
**Continue scheduled DCA at the standard size; do not chase or pause.** A larger one-shot buy is not warranted here — entry timing on a passive index ETF rarely beats consistent dollar-cost averaging at this position size.

---
*This memo was generated locally. Replace ANTHROPIC_API_KEY in .env to upgrade to live Claude analysis.*
"""


def run_research_agent(query: str) -> dict:
    """
    Generate a research memo. Saves to DB and (if configured) Obsidian.
    """
    ctx = _build_context(query)
    context_brief = _format_context_brief(ctx)

    if _has_api_key():
        client = _client()
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=RESEARCH_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Question: {query}\n\nContext:\n{context_brief}\n\nWrite the memo now."
            }]
        )
        memo = msg.content[0].text
    else:
        memo = _canned_research_memo(query, ctx)

    # Persist
    slug = re.sub(r'[^\w\s-]', '', query.lower())[:60]
    slug = re.sub(r'\s+', '-', slug.strip())
    obsidian_path = f"Research/{datetime.now():%Y-%m-%d}-{slug}.md"

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO research_memos (query, content, related_ticker, obsidian_path)
               VALUES (?, ?, ?, ?)""",
            (query, memo, ctx["portfolio"]["holdings"][0]["ticker"] if ctx["portfolio"]["holdings"] else None,
             obsidian_path)
        )
        conn.commit()
        memo_id = cur.lastrowid
    finally:
        conn.close()

    # Try to write to Obsidian vault
    written_to_vault = _try_write_obsidian(obsidian_path, memo, {
        "type": "research_memo",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "query": query,
    })

    return {
        "id": memo_id,
        "query": query,
        "memo": memo,
        "obsidian_path": obsidian_path,
        "written_to_vault": written_to_vault,
        "used_real_claude": _has_api_key(),
    }


# ─── INVESTMENT COMMITTEE ──────────────────────────────────────────

BULL_SYSTEM = """You are the Bull Analyst on a small investment committee.
Your job: make the strongest evidence-based case for buying or holding more of the position.
- Cite specific data points (price levels, recent moves, news).
- Acknowledge counterpoints briefly but argue your side.
- Maximum 180 words.
- Plain prose. No headers, no bullet lists."""

BEAR_SYSTEM = """You are the Bear Analyst on a small investment committee.
Your job: make the strongest evidence-based case for caution, reducing, or waiting.
- Cite specific risks (macro, valuation, concentration, technicals).
- Acknowledge bullish points briefly but argue your side.
- Maximum 180 words.
- Plain prose. No headers, no bullet lists."""

RISK_SYSTEM = """You are the Risk Manager on a small investment committee for a 23-year-old retail investor.
Your job: assess the user-specific risk (NOT market risk — that's the Bear's job).
Focus on: cash position, monthly budget pressure, outstanding reimbursements, position concentration, time horizon.
- Reference specific numbers from the user's data.
- Be direct about whether their personal situation supports the trade size.
- Maximum 180 words.
- Plain prose. No headers, no bullet lists."""

PM_SYSTEM = """You are the Portfolio Manager. The Bull, Bear, and Risk Manager have all reported.
Your job: synthesize their views and make a clear final decision.
- State the verdict in one sentence: "Buy X shares" / "Hold current position" / "Sell Y shares" / "Wait until Z".
- Then give 2-3 sentences of reasoning that explicitly weighs the three inputs.
- Maximum 150 words.
- Plain prose. No headers."""


def _canned_committee(query: str, ctx: dict) -> dict:
    """Realistic canned debate for demos without API key."""
    p = ctx["portfolio"]["holdings"][0] if ctx["portfolio"]["holdings"] else {}
    s = ctx["spending"]
    return_pct = p.get("total_return_pct", 0)
    return {
        "bull": (
            f"The position is up {return_pct}% from cost, which is healthy but well below "
            f"the 30%+ region where you'd start trimming. Recent price action — currently "
            f"₩{p.get('current_price', 0):,.0f}/share — sits roughly in the upper half of the "
            f"30-day range, suggesting buyers are still in control. With S&P 500 at fresh highs "
            f"and Korean retail flows turning positive (Korea Herald: 280B won net inflow in April), "
            f"momentum and structural demand both lean constructive. For a long-horizon DCA program, "
            f"there's no reason to pause — pausing during uptrends is how DCA underperforms."
        ),
        "bear": (
            f"Two concerns. First, FOMC minutes this week leaned hawkish — the rate-cut path is "
            f"now further out than what was priced into equities at the recent peak. Any disappointment "
            f"on cuts could compress multiples 5–10% from here. Second, the won has weakened past 1,380 "
            f"against the dollar, which is a tailwind today but cuts both ways: a sharp reversal would "
            f"hit returns just as fast on the way down. The position is already up {return_pct}% — "
            f"there's no rush to add. Waiting one cycle and observing how the rate path resolves is "
            f"reasonable, not bearish."
        ),
        "risk": (
            f"Card B is at {next(iter([c['pct_used'] for c in s['per_card'].values() if c['pct_used']]), 0)}% "
            f"of cap with {s['days_remaining_in_month']} days left in the month — manageable but not "
            f"loose. Outstanding reimbursements: ₩{sum(r['owes'] for r in ctx['reimbursements']):,}. "
            f"Available cash for investing this cycle is real but bounded. Position concentration is "
            f"high (single ETF) but that's acceptable for a long-horizon broad-index strategy. "
            f"Recommendation: any add should be sized to the standard DCA increment, not a one-shot "
            f"buy. Avoid drawing from Card A balances waiting on reimbursement."
        ),
        "pm": (
            f"**Verdict: Continue scheduled DCA at standard size — no extra add this cycle.** "
            f"The Bull case is real but doesn't warrant deviation; the Bear's rate-path concern is "
            f"valid enough to avoid a one-shot upsize; the Risk Manager confirms cash is fine for "
            f"the regular increment but tight for anything larger. The boring answer is the right answer."
        ),
    }


def run_investment_committee(query: str) -> dict:
    """Non-streaming version. Returns full debate as a dict."""
    ctx = _build_context(query)
    context_brief = _format_context_brief(ctx)

    if _has_api_key():
        client = _client()

        def call(system: str, user: str) -> str:
            msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": user}]
            )
            return msg.content[0].text

        bull = call(BULL_SYSTEM, f"Question: {query}\n\nContext:\n{context_brief}")
        bear = call(BEAR_SYSTEM, f"Question: {query}\n\nContext:\n{context_brief}")
        risk = call(RISK_SYSTEM, f"Question: {query}\n\nContext:\n{context_brief}")
        pm_prompt = (
            f"Question: {query}\n\nContext:\n{context_brief}\n\n"
            f"BULL ANALYST said:\n{bull}\n\n"
            f"BEAR ANALYST said:\n{bear}\n\n"
            f"RISK MANAGER said:\n{risk}\n\n"
            f"Make the call."
        )
        pm = call(PM_SYSTEM, pm_prompt)
        decision = {"bull": bull, "bear": bear, "risk": risk, "pm": pm}
    else:
        decision = _canned_committee(query, ctx)

    # Persist
    slug = re.sub(r'[^\w\s-]', '', query.lower())[:60]
    slug = re.sub(r'\s+', '-', slug.strip())
    obsidian_path = f"Decisions/{datetime.now():%Y-%m-%d}-{slug}.md"

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO committee_decisions
               (query, bull_argument, bear_argument, risk_assessment,
                pm_verdict, obsidian_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (query, decision["bull"], decision["bear"], decision["risk"],
             decision["pm"], obsidian_path)
        )
        conn.commit()
        decision_id = cur.lastrowid
    finally:
        conn.close()

    # Format full memo for Obsidian
    full_memo = f"""# Investment Committee Decision
**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Query**: {query}

## Bull Analyst
{decision['bull']}

## Bear Analyst
{decision['bear']}

## Risk Manager
{decision['risk']}

## Portfolio Manager — Final Decision
{decision['pm']}
"""
    written_to_vault = _try_write_obsidian(obsidian_path, full_memo, {
        "type": "committee_decision",
        "date": datetime.now().strftime("%Y-%m-%d"),
    })

    return {
        "id": decision_id,
        "query": query,
        "rounds": decision,
        "obsidian_path": obsidian_path,
        "written_to_vault": written_to_vault,
        "used_real_claude": _has_api_key(),
    }


def stream_investment_committee(query: str) -> Iterator[dict]:
    """
    Streaming version: yields events for each agent as they complete.
    Frontend uses Server-Sent Events to render the debate live.

    Yielded events:
      {"event": "agent_start", "agent": "bull"}
      {"event": "agent_complete", "agent": "bull", "text": "..."}
      {"event": "done", "id": int, "obsidian_path": "..."}
    """
    ctx = _build_context(query)
    context_brief = _format_context_brief(ctx)

    if _has_api_key():
        client = _client()

        def call(system: str, user: str) -> str:
            msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": user}]
            )
            return msg.content[0].text

        yield {"event": "agent_start", "agent": "bull"}
        bull = call(BULL_SYSTEM, f"Question: {query}\n\nContext:\n{context_brief}")
        yield {"event": "agent_complete", "agent": "bull", "text": bull}

        yield {"event": "agent_start", "agent": "bear"}
        bear = call(BEAR_SYSTEM, f"Question: {query}\n\nContext:\n{context_brief}")
        yield {"event": "agent_complete", "agent": "bear", "text": bear}

        yield {"event": "agent_start", "agent": "risk"}
        risk = call(RISK_SYSTEM, f"Question: {query}\n\nContext:\n{context_brief}")
        yield {"event": "agent_complete", "agent": "risk", "text": risk}

        yield {"event": "agent_start", "agent": "pm"}
        pm_prompt = (
            f"Question: {query}\n\nContext:\n{context_brief}\n\n"
            f"BULL ANALYST said:\n{bull}\n\n"
            f"BEAR ANALYST said:\n{bear}\n\n"
            f"RISK MANAGER said:\n{risk}\n\nMake the call."
        )
        pm = call(PM_SYSTEM, pm_prompt)
        yield {"event": "agent_complete", "agent": "pm", "text": pm}
        rounds = {"bull": bull, "bear": bear, "risk": risk, "pm": pm}
    else:
        # Canned + simulated typing delay
        import time
        rounds = _canned_committee(query, ctx)
        for agent in ("bull", "bear", "risk", "pm"):
            yield {"event": "agent_start", "agent": agent}
            time.sleep(0.7)  # demo pacing
            yield {"event": "agent_complete", "agent": agent, "text": rounds[agent]}

    # Persist
    slug = re.sub(r'[^\w\s-]', '', query.lower())[:60]
    slug = re.sub(r'\s+', '-', slug.strip())
    obsidian_path = f"Decisions/{datetime.now():%Y-%m-%d}-{slug}.md"

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO committee_decisions
               (query, bull_argument, bear_argument, risk_assessment,
                pm_verdict, obsidian_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (query, rounds["bull"], rounds["bear"], rounds["risk"],
             rounds["pm"], obsidian_path)
        )
        conn.commit()
        decision_id = cur.lastrowid
    finally:
        conn.close()

    full_memo = f"""# Investment Committee Decision
**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Query**: {query}

## Bull Analyst
{rounds['bull']}

## Bear Analyst
{rounds['bear']}

## Risk Manager
{rounds['risk']}

## Portfolio Manager — Final Decision
{rounds['pm']}
"""
    _try_write_obsidian(obsidian_path, full_memo, {
        "type": "committee_decision",
        "date": datetime.now().strftime("%Y-%m-%d"),
    })

    yield {"event": "done", "id": decision_id, "obsidian_path": obsidian_path}


# ─── OBSIDIAN INTEGRATION ──────────────────────────────────────────

def _get_vault_path() -> str | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='obsidian_vault_path'"
        ).fetchone()
        return row["value"] if row and row["value"] else None
    finally:
        conn.close()


def _try_write_obsidian(relative_path: str, content: str, frontmatter: dict) -> bool:
    """
    Write to Obsidian vault if configured. Returns True if written.
    Silently returns False if vault path not set or write fails — this is
    expected during demo, not an error.
    """
    vault = _get_vault_path()
    if not vault:
        return False
    from pathlib import Path
    full = Path(vault) / relative_path
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        fm = "---\n" + "\n".join(f"{k}: {v}" for k, v in frontmatter.items()) + "\n---\n\n"
        full.write_text(fm + content, encoding="utf-8")
        return True
    except (OSError, PermissionError):
        return False


# ─── BRIEFING ──────────────────────────────────────────────────────

BRIEFING_SYSTEM = """You are writing a 5-line morning briefing for a busy student.
Tone: direct, factual, no fluff. Korean Won amounts use ₩ symbol with thousands separators.
Format as JSON ONLY (no markdown fences):
{
  "portfolio_line": "TIGER S&P 500 ₩X (+Y% today)",
  "budget_line": "Card B at X%, Y days left",
  "reimbursements_line": "₩X outstanding",
  "tasks_line": "X academic, Y social, Z personal today",
  "headline": "one news line"
}"""


def _canned_briefing(ctx: dict, today_view: dict) -> dict:
    p = ctx["portfolio"]
    h = p["holdings"][0] if p["holdings"] else {}
    s = ctx["spending"]
    cardB = s["per_card"].get("B", {})
    reimb_total = sum(r["owes"] for r in ctx["reimbursements"])
    return {
        "portfolio_line": f"{h.get('name', 'Portfolio')} ₩{h.get('current_price', 0):,.0f} ({'+' if h.get('day_change_pct',0)>=0 else ''}{h.get('day_change_pct', 0)}% today)",
        "budget_line": f"Card B at {cardB.get('pct_used', 0)}% — {s['days_remaining_in_month']} days left",
        "reimbursements_line": (f"₩{reimb_total:,} outstanding" if reimb_total else "All reimbursements settled"),
        "tasks_line": f"{len(today_view['academic'])} academic, {len(today_view['social'])} social, {len(today_view['personal'])} personal today",
        "headline": ctx["news"][0]["title"] if ctx["news"] else "No recent headlines",
    }


def generate_briefing() -> dict:
    """Generate (or fetch cached) briefing for today."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        cached = conn.execute(
            "SELECT content_json FROM briefings WHERE briefing_date = ?", (today,)
        ).fetchone()
        if cached:
            return {"date": today, "cached": True, **json.loads(cached["content_json"])}
    finally:
        conn.close()

    from planning_service import get_today_view
    ctx = _build_context("morning briefing")
    today_view = get_today_view()

    if _has_api_key():
        client = _client()
        prompt = (
            f"Generate today's briefing JSON.\n\n"
            f"Context:\n{_format_context_brief(ctx)}\n\n"
            f"Today's tasks: {len(today_view['academic'])} academic, "
            f"{len(today_view['social'])} social, {len(today_view['personal'])} personal."
        )
        try:
            msg = client.messages.create(
                model=CLAUDE_MODEL, max_tokens=400,
                system=BRIEFING_SYSTEM,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = msg.content[0].text.strip()
            raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
            briefing = json.loads(raw)
        except Exception:
            briefing = _canned_briefing(ctx, today_view)
    else:
        briefing = _canned_briefing(ctx, today_view)

    # Cache
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO briefings (briefing_date, content_json) VALUES (?, ?)",
            (today, json.dumps(briefing))
        )
        conn.commit()
    finally:
        conn.close()

    return {"date": today, "cached": False, **briefing}
