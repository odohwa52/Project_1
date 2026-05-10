"""
Financial OS — FastAPI bridge
Wraps the service layer so React frontend can call it over HTTP.
Endpoints map 1:1 to MCP tools (see mcp_server.py).
"""

import json
import os
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import init_db
import spending_service as spending
import planning_service as planning
import portfolio_service as portfolio
import agents


# ─── APP SETUP ─────────────────────────────────────────────────────

app = FastAPI(title="Financial OS API", version="1.0")

# CORS — allow Cloudflare Tunnel domain + local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this for production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()


# ─── HEALTH / META ─────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "name": "Financial OS",
        "status": "online",
        "claude_api": bool(os.getenv("ANTHROPIC_API_KEY")),
        "newsdata_api": bool(os.getenv("NEWSDATA_API_KEY")),
        "now": datetime.now().isoformat(),
    }


# ─── SPENDING ──────────────────────────────────────────────────────

class ExpenseLogRequest(BaseModel):
    text: str

@app.post("/api/expenses/log")
def log_expense(req: ExpenseLogRequest):
    try:
        return spending.log_expense(req.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/expenses/recent")
def recent_expenses(limit: int = 50):
    return spending.get_recent_expenses(limit)

@app.get("/api/spending/summary")
def spending_summary(period: str = "month"):
    return spending.get_spending_summary(period)

@app.get("/api/reimbursements/outstanding")
def reimbursements_outstanding():
    return spending.get_reimbursements_outstanding()

class SettleRequest(BaseModel):
    person: str
    amount: Optional[int] = None

@app.post("/api/reimbursements/settle")
def settle_reimbursement(req: SettleRequest):
    return spending.settle_reimbursement(req.person, req.amount)


# ─── PLANNING — TODOS ──────────────────────────────────────────────

class TodoCreate(BaseModel):
    content: str
    type: str = "personal"
    class_id: Optional[int] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: str = "normal"
    repeat_pattern: Optional[str] = None

@app.post("/api/todos")
def create_todo(req: TodoCreate):
    try:
        return planning.create_todo(**req.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/todos")
def list_todos(type: Optional[str] = None,
               include_completed: bool = False,
               days_ahead: Optional[int] = None):
    return planning.list_todos(todo_type=type, include_completed=include_completed,
                               days_ahead=days_ahead)

@app.post("/api/todos/{todo_id}/complete")
def complete_todo(todo_id: int):
    try:
        return planning.complete_todo(todo_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: int):
    return planning.delete_todo(todo_id)


# ─── PLANNING — CLASSES ────────────────────────────────────────────

class ClassCreate(BaseModel):
    name: str
    semester: str
    code: Optional[str] = None
    color: str = "#E8450A"

@app.post("/api/classes")
def add_class(req: ClassCreate):
    return planning.add_class(**req.dict())

@app.get("/api/classes")
def list_classes(semester: Optional[str] = None, archived: bool = False):
    return planning.list_classes(semester=semester, archived=archived)

@app.post("/api/classes/archive-semester")
def archive_semester(semester: str):
    return planning.archive_classes(semester)

@app.post("/api/classes/{class_id}/restore")
def restore_class(class_id: int):
    return planning.restore_class(class_id)


# ─── PLANNING — FRIENDS & SOCIAL ───────────────────────────────────

class FriendCreate(BaseModel):
    name: str
    notes: Optional[str] = None

@app.post("/api/friends")
def add_friend(req: FriendCreate):
    return planning.add_friend(**req.dict())

@app.get("/api/friends")
def list_friends():
    return planning.list_friends()

class PlanCreate(BaseModel):
    friend_ids: list[int]
    plan_date: str
    location: Optional[str] = None
    plan_time: Optional[str] = None
    notes: Optional[str] = None

@app.post("/api/social-plans")
def create_social_plan(req: PlanCreate):
    return planning.create_social_plan(**req.dict())

@app.get("/api/social-plans")
def list_social_plans(upcoming_only: bool = True):
    return planning.list_social_plans(upcoming_only)


# ─── TODAY VIEW (used by Home + widget) ────────────────────────────

@app.get("/api/today")
def today():
    return planning.get_today_view()


# ─── PORTFOLIO ─────────────────────────────────────────────────────

@app.get("/api/portfolio/snapshot")
def portfolio_snapshot():
    return portfolio.get_portfolio_snapshot()

@app.get("/api/news")
def news(keywords: str = "S&P 500", hours: int = 24):
    return portfolio.get_news(keywords, hours)


# ─── AGENTS ────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    query: str

@app.post("/api/research")
def research_agent(req: ResearchRequest):
    return agents.run_research_agent(req.query)

@app.post("/api/committee")
def investment_committee(req: ResearchRequest):
    return agents.run_investment_committee(req.query)

@app.post("/api/committee/stream")
def investment_committee_stream(req: ResearchRequest):
    """
    SSE stream of the committee debate.
    Each agent's response is yielded as it completes.
    """
    def event_stream():
        for event in agents.stream_investment_committee(req.query):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─── BRIEFING ──────────────────────────────────────────────────────

@app.get("/api/briefing")
def briefing():
    return agents.generate_briefing()


# ─── MEMOS / DECISIONS HISTORY ─────────────────────────────────────

@app.get("/api/research/history")
def research_history(limit: int = 20):
    from database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, query, related_ticker, obsidian_path, created_at FROM research_memos ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/research/{memo_id}")
def research_detail(memo_id: int):
    from database import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM research_memos WHERE id = ?", (memo_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Memo not found")
        return dict(row)
    finally:
        conn.close()


@app.get("/api/committee/history")
def committee_history(limit: int = 20):
    from database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, query, obsidian_path, created_at FROM committee_decisions ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/committee/{decision_id}")
def committee_detail(decision_id: int):
    from database import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM committee_decisions WHERE id = ?", (decision_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Decision not found")
        return dict(row)
    finally:
        conn.close()


# ─── SETTINGS ──────────────────────────────────────────────────────

class SettingUpdate(BaseModel):
    key: str
    value: str

@app.get("/api/settings")
def get_settings():
    from database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()

@app.post("/api/settings")
def update_setting(req: SettingUpdate):
    from database import get_connection
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (req.key, req.value)
        )
        conn.commit()
        return {"updated": req.key}
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
