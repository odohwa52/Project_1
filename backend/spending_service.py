"""
Layer 1 — Daily Spending Tracker
Natural language parsing + three-card budget tracker + reimbursement engine.
"""

import json
import re
import os
from datetime import datetime, date
from typing import Optional
from database import get_connection

# Lazy import; only loaded if Claude API is configured
try:
    import anthropic
    _CLAUDE_AVAILABLE = True
except ImportError:
    _CLAUDE_AVAILABLE = False


# ─── KOREAN MERCHANT DICTIONARY (heuristic fallback) ───────────────
# Used when Claude API isn't available, or as a fast pre-classifier
MERCHANT_HEURISTICS = {
    "gs25": ("GS25", "convenience"),
    "cu": ("CU", "convenience"),
    "7-eleven": ("7-Eleven", "convenience"),
    "olive young": ("Olive Young", "shopping"),
    "starbucks": ("Starbucks", "dining"),
    "메가커피": ("Mega Coffee", "dining"),
    "이디야": ("Ediya", "dining"),
    "kakao": ("KakaoT", "transport"),
    "uber": ("Uber", "transport"),
    "subway": ("Subway", "transport"),
    "지하철": ("Subway", "transport"),
    "버스": ("Bus", "transport"),
    "쿠팡": ("Coupang", "shopping"),
    "coupang": ("Coupang", "shopping"),
    "netflix": ("Netflix", "subscriptions"),
    "spotify": ("Spotify", "subscriptions"),
    "youtube": ("YouTube Premium", "subscriptions"),
    "openai": ("ChatGPT", "subscriptions"),
    "anthropic": ("Claude", "subscriptions"),
    "lunch": ("Restaurant", "dining"),
    "dinner": ("Restaurant", "dining"),
}

CATEGORIES = [
    "dining", "convenience", "groceries", "transport",
    "subscriptions", "shopping", "entertainment", "education",
    "health", "other"
]


# ─── PARSING ───────────────────────────────────────────────────────

def _heuristic_parse(text: str) -> dict:
    """
    Fast regex/heuristic parse — works for clean inputs without API call.
    Returns partial dict; caller should fill missing fields with Claude.
    """
    t = text.lower().strip()

    # Amount: first integer with optional thousands separators
    amount_match = re.search(r'\b(\d{1,3}(?:,\d{3})+|\d+)\b', t)
    amount = int(amount_match.group(1).replace(",", "")) if amount_match else None

    # Card: explicit "card B", "card a", or trailing single letter
    card_match = re.search(r'card\s+([abc])\b', t)
    if card_match:
        card_id = card_match.group(1).upper()
    else:
        # standalone trailing letter "olive young 34000 c"
        trailing = re.search(r'\b([abc])\s*$', t)
        card_id = trailing.group(1).upper() if trailing else None

    # Recurring keyword
    is_recurring = bool(re.search(r'\b(monthly|recurring|subscription)\b', t))

    # Reimbursement names: "split with X and Y", "with X, Y"
    reimb_names = []
    split_match = re.search(r'(?:split|share)\s+with\s+(.+?)(?:\s+card|\s*$)', t)
    if split_match:
        names_blob = split_match.group(1)
        # Split on "and", commas, ampersands
        names = re.split(r'\s*(?:,|and|&)\s*', names_blob)
        reimb_names = [n.strip().title() for n in names if n.strip()]

    # Merchant via dictionary
    merchant = None
    category = None
    for keyword, (m, c) in MERCHANT_HEURISTICS.items():
        if keyword in t:
            merchant = m
            category = c
            break

    return {
        "amount": amount,
        "card_id": card_id,
        "merchant": merchant,
        "category": category,
        "is_recurring": is_recurring,
        "reimb_names": reimb_names,
    }


def _claude_parse(text: str, partial: dict) -> dict:
    """
    Use Claude to fill in fields the heuristic missed.
    Falls back to heuristic-only if API unavailable.
    """
    if not _CLAUDE_AVAILABLE or not os.getenv("ANTHROPIC_API_KEY"):
        return partial

    # If heuristic got everything, skip the API call
    if all(partial.get(k) for k in ("amount", "card_id", "merchant", "category")):
        return partial

    client = anthropic.Anthropic()

    system = f"""You parse Korean+English expense log entries into structured JSON.

Categories: {', '.join(CATEGORIES)}

Card defaults:
- A = group/reimbursable (lunch with team, dinner with friends)
- B = daily use (default if amount is small and no card specified)
- C = larger purchases (default if amount > 50000 and no card specified)

Output ONLY valid JSON: {{"amount": int, "merchant": str, "card_id": "A"|"B"|"C", "category": str, "reimbursable": bool}}.
No prose, no markdown fences.

Already extracted (use as ground truth where present): {json.dumps(partial, ensure_ascii=False)}"""

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content": text}]
    )

    raw = msg.content[0].text.strip()
    # Strip markdown fences if Claude added them
    raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw)
        # Merge: prefer Claude on missing fields, keep heuristic on present
        for k in ("amount", "merchant", "card_id", "category"):
            if not partial.get(k) and parsed.get(k):
                partial[k] = parsed[k]
        if "reimbursable" in parsed and "reimbursable" not in partial:
            partial["reimbursable"] = parsed["reimbursable"]
        return partial
    except json.JSONDecodeError:
        return partial


def parse_expense(text: str) -> dict:
    """
    Parse natural-language expense input.
    Pipeline: heuristic → Claude (if needed) → final defaults.
    """
    parsed = _heuristic_parse(text)
    parsed = _claude_parse(text, parsed)

    # Defaults
    if not parsed.get("card_id"):
        # Card B for small amounts, C for large
        amt = parsed.get("amount", 0) or 0
        parsed["card_id"] = "C" if amt >= 50_000 else "B"

    if not parsed.get("category"):
        parsed["category"] = "other"

    if not parsed.get("merchant"):
        parsed["merchant"] = "Unknown"

    # Card A → reimbursable by default
    if parsed["card_id"] == "A" and "reimbursable" not in parsed:
        parsed["reimbursable"] = True
    parsed.setdefault("reimbursable", False)

    return parsed


# ─── PERSISTENCE ───────────────────────────────────────────────────

def log_expense(natural_language: str) -> dict:
    """
    Parse and persist an expense. Creates reimbursement records if applicable.
    Returns the saved expense + parse breakdown.
    """
    if not natural_language or not natural_language.strip():
        raise ValueError("Empty expense input")

    parsed = parse_expense(natural_language)

    if not parsed.get("amount"):
        raise ValueError(f"Could not extract amount from: {natural_language!r}")

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO expenses
               (amount, merchant, card_id, category, reimbursable,
                is_recurring, raw_input)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (parsed["amount"], parsed["merchant"], parsed["card_id"],
             parsed["category"], int(parsed["reimbursable"]),
             int(parsed.get("is_recurring", False)), natural_language)
        )
        expense_id = cur.lastrowid

        # Update merchant memory
        merchant_norm = parsed["merchant"].lower().strip()
        conn.execute(
            """INSERT INTO merchant_categories (merchant_normalized, category)
               VALUES (?, ?)
               ON CONFLICT(merchant_normalized) DO UPDATE SET
                 seen_count = seen_count + 1,
                 last_seen  = CURRENT_TIMESTAMP""",
            (merchant_norm, parsed["category"])
        )

        # Reimbursement records: split evenly among names
        reimb_names = parsed.get("reimb_names", [])
        if parsed["reimbursable"] and reimb_names:
            per_person = parsed["amount"] // (len(reimb_names) + 1)  # +1 = the user
            for name in reimb_names:
                conn.execute(
                    """INSERT INTO reimbursements
                       (person_name, amount_owed, related_expense_id)
                       VALUES (?, ?, ?)""",
                    (name, per_person, expense_id)
                )

        conn.commit()

        return {
            "id": expense_id,
            "amount": parsed["amount"],
            "merchant": parsed["merchant"],
            "card_id": parsed["card_id"],
            "category": parsed["category"],
            "reimbursable": parsed["reimbursable"],
            "reimburse_split_with": reimb_names,
            "is_recurring": parsed.get("is_recurring", False),
        }
    finally:
        conn.close()


# ─── QUERIES ───────────────────────────────────────────────────────

def get_recent_expenses(limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, amount, merchant, card_id, category, note,
                      reimbursable, created_at
               FROM expenses ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_spending_summary(period: str = "month") -> dict:
    """
    Summarize spending. period in: 'today' | 'month' | 'all'
    Returns per-card totals + budget status + category breakdown.
    """
    conn = get_connection()
    try:
        # Date filter
        if period == "today":
            where = "date(created_at) = date('now', 'localtime')"
        elif period == "month":
            where = "strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now', 'localtime')"
        else:
            where = "1=1"

        # Per-card totals
        cards = conn.execute("SELECT * FROM cards").fetchall()
        per_card = {}
        for card in cards:
            spent = conn.execute(
                f"SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE card_id = ? AND {where}",
                (card["id"],)
            ).fetchone()[0]

            cap = card["budget_max"]
            floor = card["budget_min"]
            pct = round(spent * 100.0 / cap, 1) if cap else None

            per_card[card["id"]] = {
                "label": card["label"],
                "color": card["color"],
                "spent": spent,
                "budget_max": cap,
                "budget_min": floor,
                "pct_used": pct,
                "remaining": (cap - spent) if cap else None,
                "over_budget": (spent > cap) if cap else False,
            }

        # Category breakdown (this month)
        cat_rows = conn.execute(
            f"""SELECT category, SUM(amount) as total, COUNT(*) as n
                FROM expenses WHERE {where}
                GROUP BY category ORDER BY total DESC"""
        ).fetchall()
        categories = [dict(r) for r in cat_rows]

        # Days remaining in month
        today = date.today()
        if today.month == 12:
            last_day = date(today.year + 1, 1, 1)
        else:
            last_day = date(today.year, today.month + 1, 1)
        days_remaining = (last_day - today).days

        total = sum(c["spent"] for c in per_card.values())

        return {
            "period": period,
            "total_spent": total,
            "per_card": per_card,
            "categories": categories,
            "days_remaining_in_month": days_remaining,
        }
    finally:
        conn.close()


def get_reimbursements_outstanding() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT person_name,
                      SUM(amount_owed) as total_owed,
                      SUM(amount_paid) as total_paid,
                      COUNT(*) as count,
                      MIN(created_at) as oldest
               FROM reimbursements
               WHERE status != 'settled'
               GROUP BY person_name
               HAVING total_owed > total_paid
               ORDER BY total_owed DESC"""
        ).fetchall()
        return [
            {
                "person": r["person_name"],
                "owes": r["total_owed"] - (r["total_paid"] or 0),
                "count": r["count"],
                "oldest": r["oldest"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def settle_reimbursement(person: str, amount: Optional[int] = None) -> dict:
    """
    Mark all (or up to amount) outstanding reimbursements from `person` as settled.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, amount_owed, amount_paid FROM reimbursements
               WHERE person_name = ? AND status != 'settled'
               ORDER BY created_at""",
            (person,)
        ).fetchall()

        remaining = amount
        settled_count = 0
        total_settled = 0
        for r in rows:
            owed = r["amount_owed"] - (r["amount_paid"] or 0)
            if amount is None or remaining is None:
                # Settle in full
                conn.execute(
                    """UPDATE reimbursements SET status='settled',
                       amount_paid=amount_owed,
                       settled_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (r["id"],)
                )
                total_settled += owed
                settled_count += 1
            else:
                if remaining >= owed:
                    conn.execute(
                        """UPDATE reimbursements SET status='settled',
                           amount_paid=amount_owed,
                           settled_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (r["id"],)
                    )
                    remaining -= owed
                    total_settled += owed
                    settled_count += 1
                elif remaining > 0:
                    conn.execute(
                        """UPDATE reimbursements SET status='partial',
                           amount_paid=COALESCE(amount_paid, 0) + ? WHERE id=?""",
                        (remaining, r["id"])
                    )
                    total_settled += remaining
                    remaining = 0

        conn.commit()
        return {
            "person": person,
            "settled_count": settled_count,
            "total_settled": total_settled,
        }
    finally:
        conn.close()
