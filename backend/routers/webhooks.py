"""
Webhook registration and delivery.
Bots register a URL; the server POSTs a JSON payload whenever an event occurs.

Supported events:
  message.received  – a direct message landed in the bot's inbox
"""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from supabase import Client
from typing import Optional

from auth import get_current_bot
from database import get_supabase

logger = logging.getLogger("snapclaw")
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# ── Models ────────────────────────────────────────────────────────────────

class WebhookRequest(BaseModel):
    url: str                              # target URL
    secret: Optional[str] = None         # optional signing secret (stored, echoed back)
    events: list[str] = ["message.received"]  # which events to subscribe to


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    secret: Optional[str]
    created_at: datetime


# ── Delivery helper ───────────────────────────────────────────────────────

def fire_webhook(url: str, payload: dict, secret: Optional[str] = None):
    """Called by APScheduler in background. Best-effort — errors are logged only."""
    headers = {"Content-Type": "application/json", "User-Agent": "SnapClaw/1.0"}
    if secret:
        import hashlib, hmac, json
        body = json.dumps(payload, default=str).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-SnapClaw-Signature"] = f"sha256={sig}"
    try:
        with httpx.Client(timeout=10) as c:
            r = c.post(url, json=payload, headers=headers)
            logger.info("Webhook → %s : %d", url, r.status_code)
    except Exception as exc:
        logger.warning("Webhook delivery failed to %s: %s", url, exc)


def dispatch_event(db: Client, bot_id: str, event: str, data: dict):
    """Look up registered webhooks for this bot+event and schedule delivery."""
    try:
        from scheduler import get_scheduler
        rows = (
            db.table("webhook_endpoints")
            .select("url, secret")
            .eq("bot_id", bot_id)
            .contains("events", [event])
            .execute()
        )
        payload = {"event": event, "bot_id": bot_id, "timestamp": datetime.now(timezone.utc).isoformat(), "data": data}
        for row in (rows.data or []):
            get_scheduler().add_job(
                fire_webhook,
                "date",
                run_date=datetime.now(timezone.utc),
                args=[row["url"], payload, row.get("secret")],
                misfire_grace_time=30,
            )
    except Exception as exc:
        logger.warning("dispatch_event failed: %s", exc)


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("", response_model=WebhookResponse, status_code=201)
async def register_webhook(
    payload: WebhookRequest,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Register (or upsert) a webhook URL for this bot."""
    # Upsert by URL — one row per URL per bot
    existing = (
        db.table("webhook_endpoints")
        .select("id")
        .eq("bot_id", bot["id"])
        .eq("url", payload.url)
        .execute()
    )
    if existing.data:
        row_id = existing.data[0]["id"]
        res = db.table("webhook_endpoints").update({
            "events": payload.events,
            "secret": payload.secret,
        }).eq("id", row_id).execute()
    else:
        res = db.table("webhook_endpoints").insert({
            "bot_id": bot["id"],
            "url": payload.url,
            "events": payload.events,
            "secret": payload.secret,
        }).execute()
    return WebhookResponse(**res.data[0])


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    res = db.table("webhook_endpoints").select("*").eq("bot_id", bot["id"]).execute()
    return [WebhookResponse(**r) for r in (res.data or [])]


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    res = db.table("webhook_endpoints").select("bot_id").eq("id", webhook_id).maybe_single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Webhook not found")
    if res.data["bot_id"] != bot["id"]:
        raise HTTPException(status_code=403, detail="Not your webhook")
    db.table("webhook_endpoints").delete().eq("id", webhook_id).execute()
