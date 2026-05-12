# Financial OS — MCP Server Architecture

This document accompanies the class submission. It describes the MCP server design, the tools it exposes, and how it integrates with Claude Desktop.

## Why MCP

The university course required building an MCP server with practical tool calls. Personal finance is a natural fit because it has clearly bounded operations (log a spend, list todos, run a research memo) that an LLM can dispatch deterministically while still benefiting from LLM-side reasoning over results.

## Server entry point

`backend/mcp_server.py` instantiates `FastMCP("financial-os")` and decorates 19 tools across 5 layers. Each tool is a thin wrapper around a service-layer function in `spending_service.py`, `planning_service.py`, `portfolio_service.py`, or `agents.py`. The pattern keeps the MCP surface separate from business logic so the same code can be exposed via FastAPI (`api.py`) without duplication.

## Tool inventory

### Layer 1 — Spending
- `log_expense(text)` — natural language expense parser
- `get_spending_summary(period)` — per-card totals, budget %, days remaining
- `get_recent_expenses(limit)` — recent log
- `get_reimbursements_outstanding()` — who owes the user
- `settle_reimbursement(person, amount)` — mark reimbursements paid

### Layer 2 — Planning
- `create_todo(content, type, ...)` — academic / social / personal
- `list_todos(...)` — filter by type, due window
- `complete_todo(todo_id)` — handles repeat patterns
- `add_class(name, semester, code)` — academic classes
- `list_classes()` / `archive_classes(semester)` — semester rollover
- `add_friend(name, notes)` / `list_friends()`
- `create_social_plan(friend_ids, plan_date, ...)`
- `get_today_view()` — unified surface for morning briefing

### Layer 3 — Portfolio
- `get_portfolio_snapshot()` — holdings + market values + 30D history
- `get_news(keywords, hours)` — recent headlines

### Layer 4 — Agents
- `run_research_agent(query)` — single-agent memo, writes to Obsidian
- `run_investment_committee(query)` — 4-agent debate (Bull / Bear / Risk / PM)
- `generate_briefing()` — cached morning briefing JSON

## Tool design principles

**Idempotence where possible.** `log_expense` is intentionally not idempotent (each call adds a row); but `get_spending_summary`, `list_todos`, `get_today_view` are pure reads with no side effects, so an agent can call them repeatedly during reasoning.

**Parameter naming matches user mental models.** `due_date` is `YYYY-MM-DD`, `priority` is one of three labels, `period` is `today` / `month` / `all`. The agent doesn't have to learn an ORM.

**Graceful degradation.** Agents (`run_research_agent`, `run_investment_committee`) fall back to canned-but-data-driven responses if `ANTHROPIC_API_KEY` is missing, so the server is demo-ready on a fresh checkout.

**Deterministic context shape.** All tools return JSON-serializable dicts/lists; nothing returns a Python object that requires a custom serializer.

## Claude Desktop integration

```json
{
  "mcpServers": {
    "financial-os": {
      "command": "python",
      "args": ["/absolute/path/to/financial-os/backend/mcp_server.py"]
    }
  }
}
```

Once configured, Claude Desktop discovers the tools at startup. Sample prompts that work:

- "Log 8500 GS25 card B." — calls `log_expense`
- "How much have I spent on Card B this month?" — calls `get_spending_summary`, formats response
- "Should I add ₩200K to my position this week?" — calls `run_investment_committee`, summarizes verdict
- "What's on my plate today?" — calls `get_today_view`, narrates

## Decision: separate MCP server from FastAPI

These could have shared a single ASGI app (e.g. `mcp.run_with_uvicorn(app)`), but separating them gave two demo paths:
1. **MCP-only demo** for the class submission — Claude Desktop calls tools directly.
2. **HTTP demo** for the React frontend — same business logic, served over REST.

This made it possible to ship a polished frontend without coupling it to MCP transport details.

## Database

SQLite, single file (`financial_os.db`). Schema in `database.py`. Why not Postgres: this is single-user, locally-hosted, ~1MB of data even after a year. SQLite gets out of the way. The schema includes a `merchant_categories` table that the parser updates each time it categorizes something — over time the heuristic improves without further code changes.
