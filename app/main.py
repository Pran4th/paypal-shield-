"""Shield — post-purchase trust agent. FastAPI entrypoint."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agent, demo, eta, store
from .paypal import PayPalClient, PayPalError

app = FastAPI(title="PayPal Shield")
pp = PayPalClient()
STATIC = Path(__file__).parent / "static"


@app.on_event("startup")
def startup():
    store.init()
    demo.seed()


@app.get("/api/state")
def state():
    return {
        "demo_mode": pp.demo,
        "orders": store.list_orders(),
        "interventions": store.interventions(),
        "disputes": store.list_disputes(),
        "protected_total": store.protected_total(),
        "events": store.recent_events(30),
    }


@app.post("/api/refresh")
async def refresh():
    return await agent.rescore_all()


@app.post("/api/interventions/{iid}/approve")
async def approve(iid: int):
    iv = store.get_intervention(iid)
    if not iv:
        return JSONResponse({"error": "not found"}, 404)
    order = store.get_order(iv["order_id"]) or {}
    try:
        if iv["kind"] == "post_tracking":
            tracking = order.get("tracking_number") or "1Z-PENDING"
            await pp.post_tracking(order.get("capture_id", ""), tracking)
        elif iv["kind"] in ("offer_credit", "offer_refund"):
            await pp.refund(
                order.get("capture_id", ""),
                iv.get("amount") or 0,
                note="Goodwill — thank you for your patience",
            )
        elif iv["kind"] == "buyer_message":
            # Drafted and logged; real delivery is merchant email/SMS outside PayPal,
            # or dispute send-message once a case exists.
            pass
    except PayPalError as e:
        return JSONResponse({"error": str(e)}, 502)
    store.set_intervention_status(iid, "executed")
    store.log_event("INTERVENTION.EXECUTED", iv["order_id"], iv)
    return {"ok": True}


@app.post("/api/interventions/{iid}/reject")
def reject(iid: int):
    store.set_intervention_status(iid, "rejected")
    return {"ok": True}


@app.post("/api/disputes/{dispute_id}/draft")
async def draft(dispute_id: str):
    d = store.get_dispute(dispute_id)
    if not d:
        return JSONResponse({"error": "not found"}, 404)
    text = await agent.draft_dispute_response(d)
    store.set_dispute_draft(dispute_id, text, "draft")
    return {"draft": text}


@app.post("/api/disputes/{dispute_id}/send")
async def send_dispute(dispute_id: str):
    d = store.get_dispute(dispute_id)
    if not d or not d.get("draft_response"):
        return JSONResponse({"error": "no draft"}, 400)
    try:
        await pp.dispute_send_message(dispute_id, d["draft_response"])
        await pp.dispute_provide_evidence(
            dispute_id,
            {
                "evidences": [
                    {
                        "evidence_info": {
                            "tracking_info": [
                                {
                                    "carrier_name": "UPS",
                                    "tracking_number": (store.get_order(d["order_id"]) or {}).get("tracking_number") or "1Z-PENDING",
                                }
                            ]
                        },
                        "notes": d["draft_response"][:500],
                    }
                ]
            },
        )
    except PayPalError as e:
        return JSONResponse({"error": str(e)}, 502)
    store.set_dispute_draft(dispute_id, d["draft_response"], "sent")
    store.log_event("DISPUTE.RESPONSE_SENT", dispute_id, {"status": "sent"})
    return {"ok": True}


@app.post("/webhooks/paypal")
async def webhook(request: Request):
    body = await request.json()
    verified = await pp.verify_webhook_signature(dict(request.headers), body)
    if not verified:
        return JSONResponse({"error": "bad signature"}, 401)

    et = body.get("event_type", "")
    res = body.get("resource", {})
    rid = res.get("id", "unknown")
    store.log_event(et, rid, body)

    if et == "PAYMENT.CAPTURE.COMPLETED":
        supp = res.get("supplementary_data", {}).get("related_ids", {})
        store.upsert_order({
            "order_id": supp.get("order_id", rid),
            "capture_id": rid,
            "payer_email": res.get("payee", {}).get("email_address", ""),
            "payer_name": res.get("payer", {}).get("name", {}).get("given_name", ""),
            "amount": float(res.get("amount", {}).get("value", 0)),
            "currency": res.get("amount", {}).get("currency_code", "USD"),
            "description": res.get("seller_receivable_breakdown", {}).get("paypal_fee", {}).get("value", "") or "PayPal order",
            "status": "CAPTURED",
            "ordered_at": res.get("create_time", "")[:10],
            "promised_eta": "",
            "updated_eta": "",
        })
    elif et == "CUSTOMER.DISPUTE.CREATED":
        store.upsert_dispute({
            "dispute_id": res.get("dispute_id", rid),
            "order_id": res.get("disputed_transactions", [{}])[0].get("seller_transaction_id", ""),
            "amount": float(res.get("dispute_amount", {}).get("value", 0)),
            "currency": res.get("dispute_amount", {}).get("currency_code", "USD"),
            "reason": res.get("reason", "UNKNOWN"),
            "status": res.get("status", "OPEN"),
            "stage": res.get("dispute_life_cycle_stage", "INQUIRY"),
            "response_due": res.get("seller_response_due_date", "")[:10],
        })
        # Auto-draft immediately — agent doesn't wait for a human to notice
        d = store.get_dispute(res.get("dispute_id", rid))
        if d:
            text = await agent.draft_dispute_response(d)
            store.set_dispute_draft(d["dispute_id"], text, "draft")
    await agent.rescore_all()
    return {"received": True}


@app.post("/api/eta/sync")
async def eta_sync():
    res = await eta.sync()
    await agent.rescore_all()
    return res


@app.get("/api/studio/config")
def studio_config():
    """Public config for the AG Studio page — no secrets leave here."""
    return {
        "license_key": os.environ.get("AG_STUDIO_LICENSE_KEY", ""),
        "ai_enabled": bool(os.environ.get("OPENAI_API_KEY")),
        "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
    }


@app.post("/api/ai/responses")
async def ai_responses(request: Request):
    """SSE proxy for AG Studio's OpenAI adapter: adds the key server-side,
    streams the Responses API reply straight back."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return JSONResponse({"error": {"message": "AI assistant not configured — set OPENAI_API_KEY"}}, 503)
    body = await request.json()
    body["model"] = os.environ.get("LLM_MODEL", body.get("model", "gpt-4o-mini"))
    body.setdefault("max_output_tokens", 8192)

    async def stream():
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream(
                "POST", "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
            ) as r:
                async for chunk in r.aiter_raw():
                    yield chunk

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/demo/seed")
def reseed():
    return {"seeded": demo.seed(force=True)}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
