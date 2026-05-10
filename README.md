# Financial OS

A 5-layer personal finance and decision system. Built as an MCP server with a React demo surface.

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 1   Daily spending tracker      (NL parser, 3 cards)  │
│  Layer 2   Planning                    (todos, classes, friends) │
│  Layer 3   Portfolio monitoring        (TIGER S&P 500)       │
│  Layer 4   Decision committee          (4-agent debate)      │
│  Layer 5   Access                      (PWA + Obsidian sync) │
└──────────────────────────────────────────────────────────────┘
```

## What's in the box

```
financial-os/
├── backend/
│   ├── database.py            SQLite schema + seed
│   ├── spending_service.py    NL parser, three-card budget, reimbursements
│   ├── planning_service.py    Todos, classes, friends, social plans
│   ├── portfolio_service.py   Holdings, prices (Yahoo or synthetic), news
│   ├── agents.py              Research agent + 4-agent committee + briefing
│   ├── api.py                 FastAPI bridge — REST endpoints for the frontend
│   ├── mcp_server.py          MCP server — tools for Claude Desktop / Code
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html             Single-file React app (the demo surface)
│   ├── manifest.webmanifest   PWA install manifest
│   ├── sw.js                  Service worker (offline cache)
│   ├── icon-192.png
│   ├── icon-512.png
│   └── vendor/                Local React/ReactDOM/Babel for offline use
└── docs/
```

## Quick start (10 minutes, demo without an API key)

The demo surface (`frontend/index.html`) has **localStorage-backed state**, a working JS-side expense parser, and synthetic price data — so you can show the whole flow with zero setup.

```bash
cd frontend/
python3 -m http.server 8080
# open http://localhost:8080
```

That's it. Open it and you can log expenses, add todos, run the research agent (canned but uses real numbers from your local state), and run the 4-agent committee debate. Data persists in your browser.

## Full setup (with backend, Claude API, MCP)

### 1. Install Python deps

```bash
cd backend/
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your keys
```

| Variable | What it does | Required? |
|----------|--------------|-----------|
| `ANTHROPIC_API_KEY` | Real Claude calls in agents.py | No (canned fallback) |
| `NEWSDATA_API_KEY` | Real news in portfolio_service.py | No (synthetic fallback) |
| `FINANCIAL_OS_DB` | DB file path | No (default `./financial_os.db`) |

### 3. Initialize the DB

```bash
python database.py
# Seeds 3 cards (A/B/C) and your TIGER S&P 500 holding
```

### 4. Run the API

```bash
uvicorn api:app --port 8000 --reload
# Health check: http://localhost:8000/
```

### 5. Run the MCP server (separate terminal)

```bash
python mcp_server.py
```

### 6. Add to Claude Desktop config

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the equivalent on Windows:

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

Restart Claude Desktop. It should now see `log_expense`, `get_spending_summary`, `run_investment_committee`, and ~15 other tools.

## Cloudflare Tunnel (so your phone can reach the API)

```bash
brew install cloudflared          # macOS
# or: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Then in a terminal — leave running:
cloudflared tunnel --url http://localhost:8000

# Cloudflare will print a public URL like https://harvey-balanced.trycloudflare.com
# That's the URL you'd point the frontend at when not on localhost.
```

For a permanent named tunnel (recommended once you go beyond demos):

```bash
cloudflared tunnel login
cloudflared tunnel create financial-os
# Edit ~/.cloudflared/config.yml to map a hostname
cloudflared tunnel run financial-os
```

## Obsidian integration

1. Open the **Settings** screen in the Financial OS frontend.
2. Paste the absolute path to your Obsidian vault.
3. From now on, research memos write to `<vault>/Research/YYYY-MM-DD-<slug>.md` and committee decisions write to `<vault>/Decisions/YYYY-MM-DD-<slug>.md` with frontmatter intact.

If your vault syncs across devices (iCloud, Obsidian Sync), every memo shows up on all of them automatically.

## Phone install (PWA)

### S24+ (Android, Chrome)

1. Visit your Cloudflare Tunnel URL.
2. Chrome menu → **Add to Home screen**.
3. The icon appears with the FOS wordmark, opens fullscreen, works offline.

### iPad (Safari)

1. Visit your URL.
2. Share button → **Add to Home Screen**.
3. Same — fullscreen, offline-capable.

### Widgets

A true Android home-screen widget needs either a Tasker setup or a small native wrapper. The simplest path: pin the PWA to the lock screen and use the daily briefing notification (cron job + ntfy.sh, ~5 lines).

## Demo arc (6 beats, all functional)

```
1. Phone home screen           → PWA tile + (optional) widget showing today's brief
2. Tap PWA icon                → Dashboard loads instantly from cache
3. Log an expense              → Type "8500 GS25 card B" — parses, persists, updates donuts
4. Add a todo                  → Plan screen → Add Todo → check it off
5. Run a research agent        → Portfolio screen → suggested query → memo writes to vault
6. Run the committee           → Committee screen → 4 agents debate live → decision saved
```

## Architecture notes

- **MCP server is the actual deliverable.** The FastAPI bridge and React frontend are demo wrappers; everything they do can be done by any MCP-aware client (Claude Desktop, Claude Code, custom agents).
- **Graceful degradation everywhere.** No `ANTHROPIC_API_KEY`? Agents return canned text built from your real data. No internet? Synthetic prices. No vault path? Memos just live in the DB. Demo never breaks.
- **Heuristic-first parsing.** The expense parser tries regex+merchant-dict first; only calls Claude if heuristics miss something. Saves API budget and runs offline.
- **Browser-only mode is real.** The frontend has its own JS expense parser and localStorage layer, so you can demo the whole flow without running any backend at all. Useful for a quick laptop-only show.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Frontend blank page | Open dev tools console — usually CDN block. Switch script tags from `unpkg.com` to `vendor/*.js`. |
| `mcp` import error | `pip install mcp>=1.0`. Older versions don't have `FastMCP`. |
| Yahoo Finance 0 prices | Expected on networks that block it; synthetic fallback kicks in automatically. |
| Obsidian writes silently fail | Check the path is absolute and writable. Try `ls /your/vault/Research/` after a memo run. |
| Service worker 404 | PWA only registers on http/https origins, not `file://`. Use `python3 -m http.server`. |

## License

Personal project for university coursework. Use freely for your own setup.
