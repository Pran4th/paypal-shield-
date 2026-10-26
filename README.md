# Shield — post-purchase trust agent for PayPal merchants

An AI agent that watches a merchant's PayPal orders, predicts which ones will
become chargebacks, intervenes **before** they do, and defends the ones that
slip through anyway. Built for the PayPal AI Hackathon.

**The problem:** high-ticket, long-lead-time merchants (furniture, custom goods)
get destroyed by "item not received" chargebacks — buyers go silent for weeks,
then file instead of calling. Chargeback software exists but it all reacts
*after* you lose money. Shield works upstream.

## What it does

| Job | How | PayPal APIs |
|---|---|---|
| Risk watch | Scores every open order (ETA slips, days-silent, ticket size) | Transaction Search, Orders v2 |
| Prevention | Proposes interventions: post tracking, proactive buyer update, partial credit | Add Tracking API, Payments refunds, webhooks |
| Defense | Drafts evidence-aware dispute responses, merchant approves and sends | Disputes API, `CUSTOMER.DISPUTE.CREATED` webhook |

Human-in-the-loop: nothing ships to PayPal without a merchant click.

## Quick start (demo mode — no credentials needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # DEMO_MODE=1 is the default
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000

```bash
# fire the demo moments
python scripts/simulate_webhook.py dispute    # chargeback lands → agent auto-drafts response
python scripts/simulate_webhook.py capture    # new payment lands → risk-scored
```

## Real sandbox mode

1. Create an app at the [PayPal Developer dashboard](https://developer.paypal.com/dashboard/applications/sandbox) → copy client id/secret into `.env`
2. Deploy somewhere public (e.g. Render) and register `https://yourapp/webhooks/paypal` in the dashboard, subscribed to `PAYMENT.CAPTURE.*` and `CUSTOMER.DISPUTE.*`
3. Put the webhook id in `PAYPAL_WEBHOOK_ID`, set `DEMO_MODE=0`
4. Open a test dispute from a sandbox **personal** account's Resolution Center

## Stack

FastAPI · SQLite · AG Grid Community (risk inbox) · PayPal REST sandbox ·
pluggable LLM drafting (`OPENAI_API_KEY`; template fallback without a key).

## Roadmap to the real product

- Merchant ETA feed connector (vendor stock/lead-time data) — the risk model's strongest signal
- PayPal Agent Toolkit / MCP server for the tool layer
- Buyer message delivery (email/SMS) for the `buyer_message` intervention
- PayPal Commerce Platform multiparty for marketplace merchants
