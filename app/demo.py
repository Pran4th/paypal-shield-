"""Demo seeder: a furniture merchant's order book that looks like real life.

Twelve orders across the risk spectrum — from clean to one chargeback already
in flight. Runs on DEMO_MODE with no PayPal credentials; in production the same
rows come from Transaction Search + the merchant's own ETA feed.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from . import store

FIRST = ["Ava", "Liam", "Maya", "Noah", "Isla", "Ethan", "Sofia", "Lucas", "Amara", "Owen", "Nina", "Caleb"]
LAST = ["Bennett", "Kowalski", "Reyes", "Chen", "Ortiz", "Patel", "Murphy", "Santos", "Weber", "Kim", "Adler", "Frost"]
ITEMS = [
    ("Ashley B100 3-seat sofa", 2399.00),
    ("Luonto sleeper sectional", 3299.00),
    ("Modern Heritage queen bed", 1150.00),
    ("Bernhardt dining set", 2890.00),
    ("Coaster recliner pair", 899.00),
    ("Gio Italia leather loveseat", 1750.00),
    ("ESF bedroom dresser", 980.00),
    ("Luonto ottoman", 420.00),
    ("Ashley B300 accent chair", 640.00),
    ("Modern Heritage nightstand", 310.00),
    ("Bernhardt media console", 1520.00),
    ("Coaster dining chairs (4)", 520.00),
]


def seed(force: bool = False) -> int:
    if store.list_orders() and not force:
        return 0
    random.seed(7)
    today = date.today()
    n = 0
    for i, (desc, amt) in enumerate(ITEMS):
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        ordered = today - timedelta(days=random.randint(21, 55))
        promised = ordered + timedelta(days=random.randint(28, 70))
        slips = random.choices([0, 1, 2, 3], weights=[45, 30, 18, 7])[0]
        updated = promised + timedelta(days=slips * random.randint(5, 14)) if slips else promised
        silent = random.choices(
            [random.randint(1, 7), random.randint(8, 14), random.randint(15, 28), random.randint(29, 45)],
            weights=[25, 30, 30, 15],
        )[0]
        store.upsert_order({
            "order_id": f"SBX-ORD-{1000+i}",
            "capture_id": f"CAP-{2000+i}",
            "payer_email": f"{name.split()[0].lower()}@buyer.sandbox",
            "payer_name": name,
            "amount": amt,
            "description": desc,
            "status": "CAPTURED",
            "ordered_at": ordered.isoformat(),
            "promised_eta": promised.isoformat(),
            "updated_eta": updated.isoformat(),
            "tracking_number": f"1Z{random.randint(10**8, 10**9-1)}" if slips < 2 else None,
            "days_since_buyer_contact": silent,
            "eta_slips": slips,
        })
        n += 1
    # One dispute already in flight — the demo's moment of truth
    store.upsert_dispute({
        "dispute_id": "PP-D-0042",
        "order_id": "SBX-ORD-1001",
        "amount": 3299.00,
        "currency": "USD",
        "reason": "ITEM_NOT_RECEIVED",
        "status": "OPEN",
        "stage": "INQUIRY",
        "response_due": (date.today() + timedelta(days=6)).isoformat(),
        "evidence_status": "none",
    })
    return n
