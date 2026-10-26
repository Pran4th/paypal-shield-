"""ETA feed connector — the piece PayPal can't see.

Vendor/warehouse lead-time feeds are where chargebacks actually start:
an ETA slips, nobody tells the buyer, three weeks later they file INR.

Sync accepts either a remote JSON feed (ETA_FEED_URL) or the local
demo feed at data/eta_feed.json:

    [{"order_id": "...", "eta": "YYYY-MM-DD", "note": "vendor update"}]

On every sync we bump updated_eta / eta_slips, log the change, and let
the agent re-score the book — one slipped date can flip an order red.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from . import store

FEED_URL = os.environ.get("ETA_FEED_URL", "")
LOCAL_FEED = Path(__file__).resolve().parent.parent / "data" / "eta_feed.json"


async def fetch_feed() -> list[dict]:
    if FEED_URL:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(FEED_URL)
            r.raise_for_status()
            return r.json()
    if LOCAL_FEED.exists():
        return json.loads(LOCAL_FEED.read_text())
    return []


async def sync() -> dict:
    feed = await fetch_feed()
    changed = []
    for item in feed:
        oid = item.get("order_id")
        new_eta = item.get("eta")
        if not oid or not new_eta:
            continue
        o = store.get_order(oid)
        if not o or o.get("updated_eta") == new_eta:
            continue
        slipped = bool(o.get("updated_eta") and new_eta > o["updated_eta"]) or (
            o.get("promised_eta") and new_eta > o["promised_eta"]
        )
        store.upsert_order({
            **o,
            "updated_eta": new_eta,
            "eta_slips": (o.get("eta_slips") or 0) + (1 if slipped else 0),
        })
        store.log_event(
            "ETA.SLIPPED" if slipped else "ETA.UPDATED",
            oid,
            {
                "old": o.get("updated_eta") or o.get("promised_eta"),
                "new": new_eta,
                "note": item.get("note", ""),
                "feed": FEED_URL or str(LOCAL_FEED.name),
                "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        changed.append(oid)
    return {"feed_items": len(feed), "updated": changed}
