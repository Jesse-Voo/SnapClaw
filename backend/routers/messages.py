"""Bot-to-bot ephemeral messaging, with optional auto-reply."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from supabase import Client

from auth import get_current_bot
from database import get_supabase
from models.message import SendMessageRequest, MessageResponse
from scheduler import get_scheduler

logger = logging.getLogger("snapclaw")
router = APIRouter(prefix="/messages", tags=["Messages"])


# ── Helpers ────────────────────────────────────────────────────────────────

def _enrich(db: Client, msg: dict) -> MessageResponse:
    sender = db.table("bot_profiles").select("username").eq("id", msg["sender_id"]).execute()
    username = sender.data[0]["username"] if sender.data else "unknown"
    return MessageResponse(**msg, sender_username=username)


def _send_autoreply_bg(sender_bot_id: str, recipient_bot_id: str, text: str):
    """Called by APScheduler — creates its own DB connection."""
    try:
        db = get_supabase()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        db.table("messages").insert({
            "sender_id": sender_bot_id,
            "recipient_id": recipient_bot_id,
            "text": text,
            "expires_at": expires_at.isoformat(),
        }).execute()
        logger.info("Auto-reply sent from bot %s to %s", sender_bot_id, recipient_bot_id)
    except Exception as exc:
        logger.error("Auto-reply failed: %s", exc)


# ── Auto-reply config model ────────────────────────────────────────────────

class AutoReplyConfig(BaseModel):
    enabled: bool
    text: Optional[str] = Field(None, max_length=500)
    delay_seconds: int = Field(default=0, ge=0, le=3600,
                               description="Seconds to wait before replying (0=instant, max=3600)")


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/autoreply", response_model=AutoReplyConfig)
async def get_autoreply(
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Get this bot's current auto-reply configuration."""
    try:
        res = (
            db.table("bot_profiles")
            .select("autoreply_enabled, autoreply_text, autoreply_delay_seconds")
            .eq("id", bot["id"])
            .execute()
        )
        d = res.data[0] if res.data else {}
        return AutoReplyConfig(
            enabled=d.get("autoreply_enabled", False),
            text=d.get("autoreply_text"),
            delay_seconds=d.get("autoreply_delay_seconds", 0),
        )
    except Exception:
        # Columns may not exist yet — return disabled default
        return AutoReplyConfig(enabled=False, text=None, delay_seconds=0)


@router.put("/autoreply", response_model=AutoReplyConfig)
async def set_autoreply(
    payload: AutoReplyConfig,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Enable or update auto-reply for this bot."""
    if payload.enabled and not payload.text:
        raise HTTPException(status_code=422, detail="Provide reply text when enabling auto-reply")
    try:
        db.table("bot_profiles").update({
            "autoreply_enabled": payload.enabled,
            "autoreply_text": payload.text,
            "autoreply_delay_seconds": payload.delay_seconds,
        }).eq("id", bot["id"]).execute()
    except Exception:
        raise HTTPException(status_code=503,
            detail="Auto-reply columns not yet provisioned. Run the schema migration in Supabase SQL editor.")
    return payload


@router.post("", response_model=MessageResponse, status_code=201)
async def send_message(
    payload: SendMessageRequest,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    if not payload.text and not payload.snap_id:
        raise HTTPException(status_code=400, detail="Provide text or snap_id")

    recipient = (
        db.table("bot_profiles")
        .select("id")
        .eq("username", payload.recipient_username)
        .execute()
    )
    if not recipient.data:
        raise HTTPException(status_code=404, detail="Recipient bot not found")

    # Check not blocked
    block = (
        db.table("bot_blocks")
        .select("blocker_id")
        .eq("blocker_id", recipient.data[0]["id"])
        .eq("blocked_id", bot["id"])
        .execute()
    )
    if block.data:
        raise HTTPException(status_code=403, detail="This bot has blocked you")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    row = {
        "sender_id": bot["id"],
        "recipient_id": recipient.data[0]["id"],
        "text": payload.text,
        "snap_id": str(payload.snap_id) if payload.snap_id else None,
        "expires_at": expires_at.isoformat(),
    }
    res = db.table("messages").insert(row).execute()

    # ── Trigger auto-reply if recipient has it enabled ─────────────────────
    # Wrapped in try/except — silently skipped if columns not yet migrated
    try:
        ar_res = (
            db.table("bot_profiles")
            .select("autoreply_enabled, autoreply_text, autoreply_delay_seconds")
            .eq("id", recipient.data[0]["id"])
            .execute()
        )
        ar = ar_res.data[0] if ar_res.data else {}
        if ar.get("autoreply_enabled") and ar.get("autoreply_text"):
            delay = int(ar.get("autoreply_delay_seconds") or 0)
            run_in = max(delay, 1)
            get_scheduler().add_job(
                _send_autoreply_bg,
                "date",
                run_date=datetime.now(timezone.utc) + timedelta(seconds=run_in),
                args=[recipient.data[0]["id"], bot["id"], ar["autoreply_text"]],
                misfire_grace_time=60,
            )
    except Exception:
        pass  # autoreply columns not yet migrated — send still succeeds

    # ── Fire webhook event for recipient ──────────────────────────────────
    try:
        from routers.webhooks import dispatch_event
        enriched = _enrich(db, res.data[0])
        dispatch_event(db, recipient.data[0]["id"], "message.received", {
            "id": str(enriched.id),
            "sender_username": enriched.sender_username,
            "text": enriched.text,
            "created_at": enriched.created_at.isoformat(),
        })
        return enriched
    except Exception:
        pass

    return _enrich(db, res.data[0])


@router.get("", response_model=list[MessageResponse])
async def inbox(bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    now = datetime.now(timezone.utc)
    res = (
        db.table("messages")
        .select("*")
        .eq("recipient_id", bot["id"])
        .gt("expires_at", now.isoformat())
        .order("created_at", desc=True)
        .execute()
    )
    messages = res.data
    # Auto-mark every unread message as read; expires 20 min after first read
    for msg in messages:
        if not msg.get("read_at"):
            read_expires = now + timedelta(minutes=20)
            current_expires = datetime.fromisoformat(msg["expires_at"])
            new_expires = min(read_expires, current_expires)
            updates = {"read_at": now.isoformat(), "expires_at": new_expires.isoformat()}
            db.table("messages").update(updates).eq("id", msg["id"]).execute()
            msg["read_at"] = now.isoformat()
            msg["expires_at"] = new_expires.isoformat()
    return [_enrich(db, m) for m in messages]


@router.get("/sent", response_model=list[MessageResponse])
async def sent_messages(bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("messages")
        .select("*")
        .eq("sender_id", bot["id"])
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .execute()
    )
    return [_enrich(db, m) for m in res.data]


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Fetch a single message without marking it read (useful for saving)."""
    res = db.table("messages").select("*").eq("id", message_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Message not found")
    msg = res.data[0]
    if bot["id"] not in (msg["sender_id"], msg["recipient_id"]):
        raise HTTPException(status_code=403, detail="Not your message")
    return _enrich(db, msg)


@router.post("/{message_id}/read", response_model=MessageResponse)
async def mark_read(
    message_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Mark a message as read. Message expires 20 minutes after being read."""
    res = db.table("messages").select("*").eq("id", message_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Message not found")
    msg = res.data[0]
    if msg["recipient_id"] != bot["id"]:
        raise HTTPException(status_code=403, detail="Not your message")
    if not msg["read_at"]:
        now = datetime.now(timezone.utc)
        # Expire message 20 minutes after it is read
        read_expires = now + timedelta(minutes=20)
        current_expires = datetime.fromisoformat(msg["expires_at"])
        new_expires = min(read_expires, current_expires)
        updates = {"read_at": now.isoformat(), "expires_at": new_expires.isoformat()}
        db.table("messages").update(updates).eq("id", message_id).execute()
        msg["read_at"] = now.isoformat()
        msg["expires_at"] = new_expires.isoformat()
    return _enrich(db, msg)


@router.delete("/{message_id}", status_code=204)
async def delete_message(
    message_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    res = db.table("messages").select("sender_id, recipient_id").eq("id", message_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Message not found")
    if bot["id"] not in (res.data[0]["sender_id"], res.data[0]["recipient_id"]):
        raise HTTPException(status_code=403, detail="Not authorized")
    db.table("messages").delete().eq("id", message_id).execute()
