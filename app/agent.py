"""The trust agent.

Two jobs:
1. score_orders() — reads open orders + ETA history + buyer-contact recency and
   proposes interventions for anything that smells like a future chargeback.
2. handle_dispute() — pulls order + tracking context and drafts a stage-aware
   dispute response for merchant approval.

LLM hook: if OPENAI_API_KEY is set, drafted text goes through the model.
Without a key it falls back to templates so the demo always runs.
"""

from __future__ import annotations

import os
from datetime import date

import httpx

from . import llm, store

# ---------------------------------------------------------------- LLM layer


async def draft_text(prompt: str) -> str:
    """Ask the LLM to write concise merchant-facing copy; template fallback."""
    if not llm.enabled():
        return template_text(prompt)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{llm.base()}/chat/completions",
                headers={"Authorization": f"Bearer {llm.key()}"},
                json={
                    "model": llm.model(),
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are the trust desk of a furniture retailer. "
                                "Write short, concrete, warm copy. No fluff. 2-4 sentences."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_completion_tokens": 500,
                    **llm.chat_extra(),
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return template_text(prompt)


def template_text(prompt: str) -> str:
    return (
        "Recommended action based on order signals (ETA history, contact "
        "recency, ticket size). Set OPENAI_API_KEY to have the model write "
        "tailored buyer copy here."
    )


# ------------------------------------------------------------ risk engine

def score_order(o: dict) -> tuple[int, list[str]]:
    """0-100 risk that this order becomes an INR/UNAUTHORIZED dispute."""
    score, reasons = 0, []
    silent = o.get("days_since_buyer_contact") or 0
    slips = o.get("eta_slips") or 0
    amount = o.get("amount") or 0
    promised, updated = o.get("promised_eta"), o.get("updated_eta")

    if slips >= 2:
        score += 35
        reasons.append(f"ETA slipped {slips}x")
    elif slips == 1:
        score += 20
        reasons.append("ETA slipped once")
    if silent >= 21:
        score += 30
        reasons.append(f"{silent}d since buyer contact")
    elif silent >= 14:
        score += 15
        reasons.append(f"{silent}d since buyer contact")
    if amount >= 1500:
        score += 20
        reasons.append(f"high ticket ${amount:,.0f}")
    elif amount >= 500:
        score += 10
        reasons.append(f"ticket ${amount:,.0f}")
    if promised and updated and updated > promised:
        score += 10
        reasons.append("updated ETA past promised date")
    if not o.get("tracking_number"):
        score += 5
        reasons.append("no tracking on file")

    return min(score, 100), reasons


def propose_interventions(o: dict, score: int) -> list[dict]:
    """What should the agent do about this order?"""
    acts = []
    if not o.get("tracking_number"):
        acts.append({
            "kind": "post_tracking",
            "summary": "Attach tracking to the PayPal transaction",
            "detail": "Posts carrier + tracking number via Add Tracking API — speeds fund release and counts as evidence in INR disputes.",
        })
    if o["days_since_buyer_contact"] >= 14 or o["eta_slips"] >= 1:
        acts.append({
            "kind": "buyer_message",
            "summary": "Proactive buyer update with real ETA",
            "detail": "Buyers file chargebacks when silent. A dated, honest ETA update is the cheapest dispute prevention there is.",
        })
    if score >= 60:
        acts.append({
            "kind": "offer_credit",
            "amount": round((o["amount"] or 0) * 0.05, 2),
            "summary": f"Offer partial credit (${(o['amount'] or 0)*0.05:,.0f}) to hold the order",
            "detail": "5% goodwill credit typically costs less than a chargeback fee + lost item + lost time.",
        })
    if score >= 85:
        acts.append({
            "kind": "offer_refund",
            "amount": o["amount"],
            "summary": "Recommend full refund before chargeback",
            "detail": "Risk is extreme — a voluntary refund avoids the dispute fee and the seller-protection loss.",
        })
    return acts


async def rescore_all() -> dict:
    orders = store.list_orders()
    new_proposals = 0
    for o in orders:
        score, reasons = score_order(o)
        store.set_risk(o["order_id"], score, reasons)
        # Only propose for orders crossing the line that don't have open proposals
        if score >= 40:
            existing = {
                i["kind"]
                for i in store.interventions()
                if i["order_id"] == o["order_id"] and i["status"] == "proposed"
            }
            for act in propose_interventions(o, score):
                if act["kind"] in existing:
                    continue
                detail = await draft_text(
                    f"Draft the internal note for a '{act['kind']}' on order {o['order_id']}: "
                    f"{o['payer_name']}, {o['description']}, ${o['amount']}, "
                    f"ETA {o['promised_eta']}→{o['updated_eta']}, reasons: {', '.join(reasons)}. "
                    f"Context: {act['summary']}"
                )
                store.add_intervention(
                    o["order_id"], act["kind"], act["summary"],
                    f"{act['detail']}\n\n{detail}", act.get("amount"),
                )
                new_proposals += 1
    return {"orders": len(orders), "new_proposals": new_proposals}


# ------------------------------------------------------------- dispute desk

def _evidence_summary(o: dict | None, d: dict) -> list[str]:
    ev = []
    if o:
        ev.append(f"Order {o['order_id']} — {o['description']} (${o['amount']})")
        if o.get("tracking_number"):
            ev.append(f"Tracking {o['tracking_number']} (carrier posted to PayPal)")
        ev.append(f"Promised ETA {o['promised_eta']}; updated ETA {o['updated_eta']}")
        if o.get("eta_slips"):
            ev.append(f"ETA slips: {o['eta_slips']} (buyer was informed)")
        ev.append(f"Days since last buyer contact: {o['days_since_buyer_contact']}")
    else:
        ev.append("Order record not in local store — fetch from Orders API")
    return ev


async def draft_dispute_response(dispute: dict) -> str:
    o = store.get_order(dispute["order_id"]) if dispute.get("order_id") else None
    evidence = _evidence_summary(o, dispute)
    strategy = (
        "CONTEST with evidence" if (o and o.get("tracking_number"))
        else "NEGOTIATE — offer partial credit or refund before escalation"
    )
    body = await draft_text(
        f"Dispute {dispute['dispute_id']} ({dispute.get('reason','ITEM_NOT_RECEIVED')}, "
        f"${dispute['amount']} {dispute['currency']}, due {dispute.get('response_due')}). "
        f"Strategy: {strategy}. Evidence: {'; '.join(evidence)}. "
        "Write the evidence submission note to PayPal and a separate short message to the buyer."
    )
    return (
        f"STRATEGY: {strategy}\n"
        f"DUE: {dispute.get('response_due')}\n\n"
        f"EVIDENCE\n- " + "\n- ".join(evidence) + f"\n\nDRAFT\n{body}"
    )
