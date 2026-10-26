"""PayPal sandbox API client.

Covers the API surface the trust agent needs:
  - OAuth client-credentials token (cached until near expiry)
  - Orders v2 (get order)
  - Payments v2 (partial refund)
  - Transaction Search (list_transactions)
  - Disputes v1 (list/get/send-message/provide-evidence/make-offer)
  - Add Tracking (/v2/shipping/trackers)
  - Webhook signature verification (/v1/notifications/verify-webhook-signature)

In DEMO_MODE the client returns canned responses so the app runs end-to-end
with no PayPal credentials. Set PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET for
the real sandbox.
"""

from __future__ import annotations

import base64
import os
import time

import httpx

BASE_SANDBOX = "https://api-m.sandbox.paypal.com"


class PayPalClient:
    def __init__(self) -> None:
        self.demo = os.environ.get("DEMO_MODE", "1") == "1"
        self.base = os.environ.get("PAYPAL_API_BASE", BASE_SANDBOX)
        self.client_id = os.environ.get("PAYPAL_CLIENT_ID", "")
        self.client_secret = os.environ.get("PAYPAL_CLIENT_SECRET", "")
        self.webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID", "")
        self._token: str | None = None
        self._token_exp = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def access_token(self) -> str:
        if not self.configured:
            return "demo-token"
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        auth = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        async with httpx.AsyncClient(base_url=self.base, timeout=30) as c:
            r = await c.post(
                "/v1/oauth2/token",
                headers={"Authorization": f"Basic {auth}"},
                data={"grant_type": "client_credentials"},
            )
            r.raise_for_status()
            body = r.json()
        self._token = body["access_token"]
        self._token_exp = time.time() + int(body.get("expires_in", 28800))
        return self._token

    async def _req(self, method: str, path: str, **kw):
        if self.demo:
            return self._demo(method, path, kw)
        token = await self.access_token()
        async with httpx.AsyncClient(base_url=self.base, timeout=30) as c:
            r = await c.request(
                method,
                path,
                headers={
                    "Authorization": f"Bearer {token}",
                    "PayPal-Request-Id": kw.pop("request_id", f"shield-{int(time.time()*1000)}"),
                },
                **kw,
            )
            if r.status_code >= 400:
                debug_id = r.headers.get("paypal-debug-id")
                raise PayPalError(r.status_code, r.text, debug_id)
            return r.json() if r.content else {}

    def _demo(self, method: str, path: str, kw):
        """Canned sandbox responses for DEMO_MODE."""
        if path.startswith("/v2/checkout/orders/"):
            return {"id": path.rsplit("/", 1)[-1], "status": "APPROVED"}
        if path.startswith("/v2/shipping/trackers"):
            return {"id": "DEMO-TRACK-1", "status": "SHIPPED"}
        if "/refund" in path:
            return {"id": "DEMO-REFUND-1", "status": "COMPLETED"}
        if path.startswith("/v1/customer/disputes"):
            return {"dispute_id": path.rsplit("/", 1)[-1], "status": "UNDER_REVIEW"}
        if path.startswith("/v1/reporting/transactions"):
            return {"transaction_details": [], "total_items": 0}
        if path.startswith("/v1/notifications/verify-webhook-signature"):
            return {"verification_status": "SUCCESS"}
        return {"demo": True, "path": path}

    # --- Orders / payments -------------------------------------------------
    async def get_order(self, order_id: str):
        return await self._req("GET", f"/v2/checkout/orders/{order_id}")

    async def refund(self, capture_id: str, amount: float, currency: str = "USD", note: str = ""):
        return await self._req(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            json={
                "amount": {"value": f"{amount:.2f}", "currency_code": currency},
                "note_to_payer": note[:255],
            },
        )

    # --- Transaction search -------------------------------------------------
    async def list_transactions(self, start_iso: str, end_iso: str, fields: str = "all"):
        return await self._req(
            "GET",
            "/v1/reporting/transactions",
            params={
                "start_date": start_iso,
                "end_date": end_iso,
                "fields": fields,
                "page_size": "100",
            },
        )

    # --- Tracking -----------------------------------------------------------
    async def post_tracking(self, capture_id: str, tracking_number: str, carrier: str = "OTHER", status: str = "SHIPPED"):
        return await self._req(
            "POST",
            "/v2/shipping/trackers",
            json={
                "capture_id": capture_id,
                "tracking_number": tracking_number,
                "carrier": carrier,
                "status": status,
            },
        )

    # --- Disputes -------------------------------------------------------------
    async def list_disputes(self):
        return await self._req("GET", "/v1/customer/disputes")

    async def get_dispute(self, dispute_id: str):
        return await self._req("GET", f"/v1/customer/disputes/{dispute_id}")

    async def dispute_send_message(self, dispute_id: str, message: str):
        return await self._req(
            "POST",
            f"/v1/customer/disputes/{dispute_id}/send-message",
            json={"message": message},
        )

    async def dispute_make_offer(self, dispute_id: str, amount: float, currency: str = "USD"):
        return await self._req(
            "POST",
            f"/v1/customer/disputes/{dispute_id}/make-offer",
            json={"offer_amount": {"value": f"{amount:.2f}", "currency": currency}},
        )

    async def dispute_provide_evidence(self, dispute_id: str, evidence: dict):
        return await self._req(
            "POST",
            f"/v1/customer/disputes/{dispute_id}/provide-evidence",
            json=evidence,
        )

    async def dispute_accept_claim(self, dispute_id: str, note: str = ""):
        return await self._req(
            "POST",
            f"/v1/customer/disputes/{dispute_id}/accept-claim",
            json={"note": note},
        )

    # --- Webhooks -------------------------------------------------------------
    async def verify_webhook_signature(self, headers: dict, raw_body: str) -> bool:
        if self.demo:
            return True
        token = await self.access_token()
        async with httpx.AsyncClient(base_url=self.base, timeout=30) as c:
            r = await c.post(
                "/v1/notifications/verify-webhook-signature",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "transmission_id": headers.get("paypal-transmission-id"),
                    "transmission_time": headers.get("paypal-transmission-time"),
                    "cert_url": headers.get("paypal-cert-url"),
                    "auth_algo": headers.get("paypal-auth-algo"),
                    "transmission_sig": headers.get("paypal-transmission-sig"),
                    "webhook_id": self.webhook_id,
                    "webhook_event": raw_body if isinstance(raw_body, dict) else None,
                },
            )
            return r.status_code == 200 and r.json().get("verification_status") == "SUCCESS"


class PayPalError(Exception):
    def __init__(self, status: int, body: str, debug_id: str | None):
        super().__init__(f"PayPal {status} (debug_id={debug_id}): {body[:400]}")
        self.status = status
        self.debug_id = debug_id
