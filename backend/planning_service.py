"""
Layer 2 — To-Do & Planning
Academic tracker, social planner, personal reminders, all unified surface.
"""

import json
from datetime import datetime, date, timedelta
from typing import Optional
from database import get_connection


# ─── CLASSES ───────────────────────────────────────────────────────

def add_class(name: str, semester: str, code: Optional[str] = None,
              color: str = "#E8450A") -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO classes (name, semester, code, color) VALUES (?, ?, ?, ?)",
            (name, semester, code, color)
        )
        conn.commit()
        return {"id": cur.lastrowid, "name": name, "semester": semester, "code": code, "color": color}
    finally:
        conn.close()


def list_classes(semester: Optional[str] = None, archived: bool = False) -> list[dict]:
    conn = get_connection()
    try:
        q = "SELECT * FROM classes WHERE archived = ?"
        params = [int(archived)]
        if semester:
            q += " AND semester = ?"
            params.append(semester)
        q += " ORDER BY name"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def archive_classes(semester: str) -> dict:
    """Bulk archive — used at semester rollover."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE classes SET archived = 1 WHERE semester = ? AND archived = 0",
            (semester,)
        )
        conn.commit()
        return {"archived_count": cur.rowcount, "semester": semester}
    finally:
        conn.close()


def restore_class(class_id: int) -> dict:
    conn = get_connection()
    try:
        conn.execute("UPDATE classes SET archived = 0 WHERE id = ?", (class_id,))
        conn.commit()
        return {"restored": class_id}
    finally:
        conn.close()


# ─── TODOS ─────────────────────────────────────────────────────────

def create_todo(content: str, todo_type: str = "personal",
                class_id: Optional[int] = None,
                due_date: Optional[str] = None,
                due_time: Optional[str] = None,
                priority: str = "normal",
                repeat_pattern: Optional[str] = None) -> dict:
    if todo_type not in ("academic", "social", "personal"):
        raise ValueError(f"Invalid todo type: {todo_type}")
    if priority not in ("low", "normal", "high"):
        priority = "normal"

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO todos
               (content, type, class_id, due_date, due_time, priority, repeat_pattern)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (content, todo_type, class_id, due_date, due_time, priority, repeat_pattern)
        )
        conn.commit()
        return {"id": cur.lastrowid, "content": content, "type": todo_type,
                "due_date": due_date, "priority": priority}
    finally:
        conn.close()


def list_todos(todo_type: Optional[str] = None,
               include_completed: bool = False,
               days_ahead: Optional[int] = None) -> list[dict]:
    conn = get_connection()
    try:
        q = """SELECT t.*, c.name as class_name, c.color as class_color
               FROM todos t
               LEFT JOIN classes c ON t.class_id = c.id
               WHERE t.archived = 0"""
        params = []
        if todo_type:
            q += " AND t.type = ?"
            params.append(todo_type)
        if not include_completed:
            q += " AND t.completed = 0"
        if days_ahead is not None:
            cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()
            q += " AND (t.due_date IS NULL OR t.due_date <= ?)"
            params.append(cutoff)
        q += " ORDER BY t.completed, t.due_date IS NULL, t.due_date, t.priority DESC"

        rows = conn.execute(q, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            # Add urgency flag
            d["urgency"] = _urgency_for(d.get("due_date"))
            results.append(d)
        return results
    finally:
        conn.close()


def _urgency_for(due_date_str: Optional[str]) -> Optional[str]:
    if not due_date_str:
        return None
    try:
        due = datetime.fromisoformat(due_date_str).date()
    except (ValueError, TypeError):
        return None
    today = date.today()
    delta = (due - today).days
    if delta < 0:
        return "overdue"
    elif delta == 0:
        return "today"
    elif delta == 1:
        return "tomorrow"
    elif delta <= 3:
        return "soon"
    return None


def complete_todo(todo_id: int) -> dict:
    conn = get_connection()
    try:
        # Get the todo first to handle repeat patterns
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        if not row:
            raise ValueError(f"No todo {todo_id}")

        conn.execute(
            """UPDATE todos SET completed = 1, completed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (todo_id,)
        )

        # Repeat pattern: spawn a new instance
        new_id = None
        if row["repeat_pattern"] and row["due_date"]:
            new_due = _next_occurrence(row["due_date"], row["repeat_pattern"])
            if new_due:
                cur = conn.execute(
                    """INSERT INTO todos
                       (content, type, class_id, due_date, due_time, priority, repeat_pattern)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (row["content"], row["type"], row["class_id"],
                     new_due, row["due_time"], row["priority"], row["repeat_pattern"])
                )
                new_id = cur.lastrowid

        conn.commit()
        return {"completed": todo_id, "spawned_next": new_id}
    finally:
        conn.close()


def _next_occurrence(date_str: str, pattern: str) -> Optional[str]:
    try:
        d = datetime.fromisoformat(date_str).date()
    except ValueError:
        return None
    if pattern == "daily":
        return (d + timedelta(days=1)).isoformat()
    if pattern == "weekly":
        return (d + timedelta(days=7)).isoformat()
    if pattern.startswith("monthly"):
        # Move to same day next month
        if d.month == 12:
            return d.replace(year=d.year + 1, month=1).isoformat()
        try:
            return d.replace(month=d.month + 1).isoformat()
        except ValueError:
            # E.g. Jan 31 → Feb 28
            return (d + timedelta(days=30)).isoformat()
    return None


def delete_todo(todo_id: int) -> dict:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        conn.commit()
        return {"deleted": todo_id}
    finally:
        conn.close()


# ─── FRIENDS ───────────────────────────────────────────────────────

def add_friend(name: str, notes: Optional[str] = None) -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO friends (name, notes) VALUES (?, ?)", (name, notes)
        )
        conn.commit()
        return {"id": cur.lastrowid, "name": name, "notes": notes}
    finally:
        conn.close()


def list_friends() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM friends ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── SOCIAL PLANS ──────────────────────────────────────────────────

def create_social_plan(friend_ids: list[int], plan_date: str,
                       location: Optional[str] = None,
                       plan_time: Optional[str] = None,
                       notes: Optional[str] = None) -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO social_plans
               (friend_ids, plan_date, plan_time, location, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (json.dumps(friend_ids), plan_date, plan_time, location, notes)
        )
        conn.commit()
        return {"id": cur.lastrowid, "friend_ids": friend_ids,
                "plan_date": plan_date, "location": location}
    finally:
        conn.close()


def list_social_plans(upcoming_only: bool = True) -> list[dict]:
    conn = get_connection()
    try:
        q = """SELECT p.*, GROUP_CONCAT(f.name, ', ') as friend_names
               FROM social_plans p"""
        if upcoming_only:
            q += " WHERE p.plan_date >= date('now', 'localtime')"
        q += " ORDER BY p.plan_date, p.plan_time"
        rows = conn.execute(q).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            ids = json.loads(d.get("friend_ids", "[]"))
            d["friend_ids"] = ids
            # Resolve friend names
            if ids:
                friend_rows = conn.execute(
                    f"SELECT name FROM friends WHERE id IN ({','.join('?' * len(ids))})",
                    ids
                ).fetchall()
                d["friend_names"] = ", ".join(r["name"] for r in friend_rows)
            else:
                d["friend_names"] = ""
            results.append(d)
        return results
    finally:
        conn.close()


# ─── UNIFIED "TODAY" VIEW ──────────────────────────────────────────

def get_today_view() -> dict:
    """
    Unified surface for morning briefing and dashboard.
    Returns: academic deadlines (3 days), today's social plans, today's personal todos.
    """
    today = date.today().isoformat()

    # Academic: due within 3 days
    academic = list_todos(todo_type="academic", days_ahead=3)

    # Personal: due today or no due date with high priority
    conn = get_connection()
    try:
        personal_rows = conn.execute(
            """SELECT t.*, NULL as class_name, NULL as class_color
               FROM todos t
               WHERE t.type = 'personal' AND t.completed = 0 AND t.archived = 0
                 AND (t.due_date = ? OR (t.due_date IS NULL AND t.priority = 'high'))
               ORDER BY t.priority DESC""",
            (today,)
        ).fetchall()
        personal = [dict(r) for r in personal_rows]

        # Social plans today
        social_rows = conn.execute(
            "SELECT * FROM social_plans WHERE plan_date = ?",
            (today,)
        ).fetchall()
        social = []
        for r in social_rows:
            d = dict(r)
            ids = json.loads(d.get("friend_ids", "[]"))
            if ids:
                fr = conn.execute(
                    f"SELECT name FROM friends WHERE id IN ({','.join('?' * len(ids))})",
                    ids
                ).fetchall()
                d["friend_names"] = ", ".join(f["name"] for f in fr)
            social.append(d)
    finally:
        conn.close()

    return {
        "date": today,
        "academic": academic,
        "social": social,
        "personal": personal,
        "total_count": len(academic) + len(social) + len(personal),
    }
