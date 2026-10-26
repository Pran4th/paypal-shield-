"""SQLite store: orders, tracking/ETA data, events, interventions, disputes."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "shield.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    capture_id TEXT,
    payer_email TEXT,
    payer_name TEXT,
    amount REAL,
    currency TEXT DEFAULT 'USD',
    description TEXT,
    status TEXT,
    ordered_at TEXT,
    promised_eta TEXT,
    updated_eta TEXT,
    tracking_number TEXT,
    days_since_buyer_contact INTEGER DEFAULT 0,
    eta_slips INTEGER DEFAULT 0,
    risk_score INTEGER DEFAULT 0,
    risk_reasons TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    kind TEXT,
    status TEXT DEFAULT 'proposed',
    summary TEXT,
    detail TEXT,
    amount REAL,
    created_at TEXT,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS disputes (
    dispute_id TEXT PRIMARY KEY,
    order_id TEXT,
    amount REAL,
    currency TEXT,
    reason TEXT,
    status TEXT,
    stage TEXT,
    response_due TEXT,
    evidence_status TEXT DEFAULT 'none',
    draft_response TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT,
    resource_id TEXT,
    payload TEXT,
    received_at TEXT
);
"""


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def upsert_order(o: dict) -> None:
    cols = [
        "order_id", "capture_id", "payer_email", "payer_name", "amount",
        "currency", "description", "status", "ordered_at", "promised_eta",
        "updated_eta", "tracking_number", "days_since_buyer_contact",
        "eta_slips", "risk_score", "risk_reasons",
    ]
    row = {k: o.get(k) for k in cols}
    row["risk_reasons"] = json.dumps(row.get("risk_reasons") or [])
    with db() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO orders ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
            [row[k] for k in cols],
        )


def list_orders() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY risk_score DESC"
        ).fetchall()
    return [{**dict(r), "risk_reasons": json.loads(r["risk_reasons"])} for r in rows]


def get_order(order_id: str) -> dict | None:
    with db() as conn:
        r = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not r:
        return None
    return {**dict(r), "risk_reasons": json.loads(r["risk_reasons"])}


def set_risk(order_id: str, score: int, reasons: list[str]) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE orders SET risk_score=?, risk_reasons=? WHERE order_id=?",
            (score, json.dumps(reasons), order_id),
        )


def add_intervention(order_id: str, kind: str, summary: str, detail: str, amount: float | None) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO interventions (order_id,kind,summary,detail,amount,created_at) VALUES (?,?,?,?,?,?)",
            (order_id, kind, summary, detail, amount, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )
        return cur.lastrowid


def interventions(status: str | None = None) -> list[dict]:
    q = "SELECT * FROM interventions"
    params: tuple = ()
    if status:
        q += " WHERE status=?"
        params = (status,)
    q += " ORDER BY id DESC"
    with db() as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def get_intervention(iid: int) -> dict | None:
    with db() as conn:
        r = conn.execute("SELECT * FROM interventions WHERE id=?", (iid,)).fetchone()
    return dict(r) if r else None


def set_intervention_status(iid: int, status: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE interventions SET status=?, decided_at=? WHERE id=?",
            (status, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), iid),
        )


def upsert_dispute(d: dict) -> None:
    cols = [
        "dispute_id", "order_id", "amount", "currency", "reason",
        "status", "stage", "response_due", "evidence_status", "draft_response",
    ]
    row = {k: d.get(k) for k in cols}
    with db() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO disputes ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
            [row[k] for k in cols],
        )


def list_disputes() -> list[dict]:
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM disputes ORDER BY response_due").fetchall()]


def get_dispute(dispute_id: str) -> dict | None:
    with db() as conn:
        r = conn.execute("SELECT * FROM disputes WHERE dispute_id=?", (dispute_id,)).fetchone()
    return dict(r) if r else None


def set_dispute_draft(dispute_id: str, draft: str, evidence_status: str = "draft") -> None:
    with db() as conn:
        conn.execute(
            "UPDATE disputes SET draft_response=?, evidence_status=? WHERE dispute_id=?",
            (draft, evidence_status, dispute_id),
        )


def log_event(event_type: str, resource_id: str, payload: dict) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO events (event_type, resource_id, payload, received_at) VALUES (?,?,?,?)",
            (event_type, resource_id, json.dumps(payload), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )


def recent_events(limit: int = 50) -> list[dict]:
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]


def protected_total() -> float:
    """Dollars at risk on orders where an intervention was approved + disputes responded."""
    with db() as conn:
        r1 = conn.execute(
            "SELECT COALESCE(SUM(o.amount),0) FROM interventions i JOIN orders o ON o.order_id=i.order_id WHERE i.status='executed'"
        ).fetchone()[0]
        r2 = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM disputes WHERE evidence_status IN ('sent','won')"
        ).fetchone()[0]
    return round(r1 + r2, 2)
