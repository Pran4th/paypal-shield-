#!/usr/bin/env python3
"""Simulate PayPal webhook deliveries against a running Shield instance.

Usage:
    python scripts/simulate_webhook.py capture   # a new payment lands
    python scripts/simulate_webhook.py dispute   # a chargeback lands -> agent auto-drafts response
    python scripts/simulate_webhook.py dispute PP-D-0099 SBX-ORD-1002 1500.00

In real life these payloads come from PayPal to your public /webhooks/paypal URL.
In demo we POST them ourselves — same code path.
"""

import json
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--base" else "http://localhost:8000"


def post(payload: dict) -> None:
    req = urllib.request.Request(
        f"{BASE}/webhooks/paypal",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print(json.dumps(payload, indent=2)[:600], "…")
    print("→", urllib.request.urlopen(req).read().decode())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capture(order_id="SBX-ORD-1099", capture_id="CAP-2099", amount="1849.00"):
    post({
        "id": f"WH-DEMO-{order_id}",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "create_time": now(),
        "resource": {
            "id": capture_id,
            "amount": {"value": amount, "currency_code": "USD"},
            "payee": {"email_address": "merchant@artisan-furniture.sandbox"},
            "payer": {"name": {"given_name": "Jordan", "surname": "Ellis"}},
            "create_time": now(),
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    })


def dispute(dispute_id="PP-D-0099", order_id="SBX-ORD-1002", amount="1150.00"):
    post({
        "id": f"WH-DEMO-{dispute_id}",
        "event_type": "CUSTOMER.DISPUTE.CREATED",
        "create_time": now(),
        "resource": {
            "dispute_id": dispute_id,
            "dispute_life_cycle_stage": "INQUIRY",
            "reason": "ITEM_NOT_RECEIVED",
            "status": "OPEN",
            "dispute_amount": {"value": amount, "currency_code": "USD"},
            "seller_response_due_date": (date.today() + timedelta(days=10)).isoformat() + "T00:00:00Z",
            "disputed_transactions": [{"seller_transaction_id": order_id}],
        },
    })


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "dispute"
    if kind == "capture":
        capture(*sys.argv[2:4]) if len(sys.argv) > 3 else capture()
    else:
        dispute(*sys.argv[2:5]) if len(sys.argv) > 4 else dispute()
