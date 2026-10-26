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
| ETA feed | Syncs vendor lead-time updates (`/api/eta/sync`) — the signal PayPal can't see | ETA_FEED_URL or `data/eta_feed.json` |
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
curl -X POST http://localhost:8000/api/eta/sync  # vendor ETA feed sync → two orders slip, risk jumps
```

## AG Studio (sponsor surface — $5k Best Use of AG Studio)

`/studio.html` embeds **AG Studio** over the same `/api/state` data: orders,
interventions, disputes and the event log as related data sources, with
cross-filtering and self-serve widgets. With `OPENAI_API_KEY` set, the
**Studio Agent Framework** assistant lights up — it can query, chart and edit
the dashboard through our `/api/ai/responses` SSE proxy (key never reaches the
browser). Needs an `AG_STUDIO_LICENSE_KEY` (free trial from AG Grid).

## Deploy (Render, one file)

`render.yaml` is in the repo — New → Blueprint on [Render](https://render.com),
paste the repo URL, fill the env vars marked `sync: false`. Ships with
`DEMO_MODE=1` so it works before you wire sandbox credentials.

## Real sandbox mode

1. Create an app at the [PayPal Developer dashboard](https://developer.paypal.com/dashboard/applications/sandbox) → copy client id/secret into `.env`
2. Deploy somewhere public (e.g. Render) and register `https://yourapp/webhooks/paypal` in the dashboard, subscribed to `PAYMENT.CAPTURE.*` and `CUSTOMER.DISPUTE.*`
3. Put the webhook id in `PAYPAL_WEBHOOK_ID`, set `DEMO_MODE=0`
4. Open a test dispute from a sandbox **personal** account's Resolution Center

## Stack

FastAPI · SQLite · AG Grid Community (risk inbox) · PayPal REST sandbox ·
pluggable LLM drafting (`OPENAI_API_KEY`; template fallback without a key).

## Roadmap to the real product

- ETA feed → real vendor connectors (Shopify metafields, supplier EDI)
- PayPal Agent Toolkit / MCP server for the tool layer
- Buyer message delivery (email/SMS) for the `buyer_message` intervention
- PayPal Commerce Platform multiparty for marketplace merchants
