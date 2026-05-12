"""
Financial OS — MCP Server
Exposes the same operations as api.py but as MCP tools, so Claude Desktop /
Claude Code can call them directly. This is the actual class deliverable.

Run with: python mcp_server.py
Or via Claude Desktop config:
  {
    "mcpServers": {
      "financial-os": {
        "command": "python",
        "args": ["/path/to/financial-os/backend/mcp_server.py"]
      }
    }
  }
"""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from database import init_db
import spending_service as spending
import planning_service as planning
import portfolio_service as portfolio
import agents


init_db()

mcp = FastMCP("financial-os")


# ─── SPENDING TOOLS ────────────────────────────────────────────────

@mcp.tool()
def log_expense(text: str) -> dict:
    """
    Log an expense from natural language.

    Examples that work:
      - "8500 GS25 card B"
      - "lunch with team 45000 card A — split with junho and minji"
      - "subway 1500"
      - "olive young 34000 c"
      - "netflix 17000 monthly card c"

    Returns the parsed expense with id, amount, merchant, card_id, category,
    reimbursable status, and any reimbursement records created.
    """
    return spending.log_expense(text)


@mcp.tool()
def get_spending_summary(period: str = "month") -> dict:
    """
    Summarize spending. period in ('today', 'month', 'all').
    Returns per-card totals, budget %, days remaining in month, category breakdown.
    """
    return spending.get_spending_summary(period)


@mcp.tool()
def get_recent_expenses(limit: int = 50) -> list[dict]:
    """List most recent expenses, newest first."""
    return spending.get_recent_expenses(limit)


@mcp.tool()
def get_reimbursements_outstanding() -> list[dict]:
    """Who owes you money and how much. Sorted by amount owed descending."""
    return spending.get_reimbursements_outstanding()


@mcp.tool()
def settle_reimbursement(person: str, amount: Optional[int] = None) -> dict:
    """
    Mark reimbursements from `person` as settled. If amount is None, settles all
    outstanding from that person. Otherwise settles up to `amount`.
    """
    return spending.settle_reimbursement(person, amount)


# ─── PLANNING TOOLS ────────────────────────────────────────────────

@mcp.tool()
def create_todo(content: str, type: str = "personal",
                class_id: Optional[int] = None,
                due_date: Optional[str] = None,
                due_time: Optional[str] = None,
                priority: str = "normal",
                repeat_pattern: Optional[str] = None) -> dict:
    """
    Create a todo. type must be one of: academic, social, personal.
    due_date in YYYY-MM-DD; due_time in HH:MM.
    repeat_pattern in: daily, weekly, monthly.
    priority in: low, normal, high.
    """
    return planning.create_todo(
        content=content, todo_type=type, class_id=class_id,
        due_date=due_date, due_time=due_time, priority=priority,
        repeat_pattern=repeat_pattern
    )


@mcp.tool()
def list_todos(type: Optional[str] = None,
               include_completed: bool = False,
               days_ahead: Optional[int] = None) -> list[dict]:
    """List todos. Filter by type, completion status, or due-within-N-days."""
    return planning.list_todos(todo_type=type, include_completed=include_completed,
                               days_ahead=days_ahead)


@mcp.tool()
def complete_todo(todo_id: int) -> dict:
    """Mark a todo as complete. Spawns next instance if it has a repeat pattern."""
    return planning.complete_todo(todo_id)


@mcp.tool()
def add_class(name: str, semester: str, code: Optional[str] = None,
              color: str = "#E8450A") -> dict:
    """Add a class. Semester format: 'YYYY-N' like '2026-1'."""
    return planning.add_class(name=name, semester=semester, code=code, color=color)


@mcp.tool()
def list_classes(semester: Optional[str] = None, archived: bool = False) -> list[dict]:
    """List classes. archived=True shows archived classes."""
    return planning.list_classes(semester=semester, archived=archived)


@mcp.tool()
def archive_classes(semester: str) -> dict:
    """Bulk-archive every class in a semester. Used at semester rollover."""
    return planning.archive_classes(semester)


@mcp.tool()
def add_friend(name: str, notes: Optional[str] = None) -> dict:
    """Add a friend. notes is optional context."""
    return planning.add_friend(name=name, notes=notes)


@mcp.tool()
def list_friends() -> list[dict]:
    """List all friends, alphabetical."""
    return planning.list_friends()


@mcp.tool()
def create_social_plan(friend_ids: list[int], plan_date: str,
                       location: Optional[str] = None,
                       plan_time: Optional[str] = None,
                       notes: Optional[str] = None) -> dict:
    """
    Create a social plan. friend_ids is a list of friend IDs (use list_friends to discover).
    plan_date is YYYY-MM-DD; plan_time is HH:MM.
    """
    return planning.create_social_plan(
        friend_ids=friend_ids, plan_date=plan_date,
        location=location, plan_time=plan_time, notes=notes
    )


@mcp.tool()
def get_today_view() -> dict:
    """
    Unified 'today' surface: academic deadlines (next 3 days), today's social plans,
    today's personal todos. Used by morning briefing and the home dashboard.
    """
    return planning.get_today_view()


# ─── PORTFOLIO TOOLS ───────────────────────────────────────────────

@mcp.tool()
def get_portfolio_snapshot() -> dict:
    """
    Current portfolio state: holdings, market values, P&L, daily change,
    30-day price history.
    """
    return portfolio.get_portfolio_snapshot()


@mcp.tool()
def get_news(keywords: str = "S&P 500", hours: int = 24) -> list[dict]:
    """Fetch news related to keywords from the last N hours."""
    return portfolio.get_news(keywords, hours)


# ─── AGENT TOOLS ───────────────────────────────────────────────────

@mcp.tool()
def run_research_agent(query: str) -> dict:
    """
    Run the research agent. Pulls portfolio + spending + news context, generates
    a structured memo, writes to Obsidian if configured.
    Returns the memo content + obsidian_path.
    """
    return agents.run_research_agent(query)


@mcp.tool()
def run_investment_committee(query: str) -> dict:
    """
    Run the four-agent committee (Bull, Bear, Risk, PM). Returns full debate
    rounds + PM verdict. Writes decision memo to Obsidian if configured.
    """
    return agents.run_investment_committee(query)


@mcp.tool()
def generate_briefing() -> dict:
    """
    Generate today's morning briefing. Returns structured JSON with portfolio
    line, budget line, reimbursements, tasks count, and a headline.
    Cached per day.
    """
    return agents.generate_briefing()


if __name__ == "__main__":
    mcp.run()
