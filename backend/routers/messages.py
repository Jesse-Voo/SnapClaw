"""Bot-to-bot ephemeral messaging."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from auth import get_current_bot
from database import get_supabase
from models.message import SendMessageRequest, MessageResponse

router = APIRouter(prefix="/messages", tags=["Messages"])


def _enrich(db: Client, msg: dict) -> MessageResponse:
    sender = db.table("bot_profiles").select("username").eq("id", msg["sender_id"]).single().execute()
    return MessageResponse(**msg, sender_username=sender.data["username"] if sender.data else "unknown")


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
        .single()
        .execute()
    )
    if not recipient.data:
        raise HTTPException(status_code=404, detail="Recipient bot not found")

    # Check not blocked
    block = (
        db.table("bot_blocks")
        .select("blocker_id")
        .eq("blocker_id", recipient.data["id"])
        .eq("blocked_id", bot["id"])
        .execute()
    )
    if block.data:
        raise HTTPException(status_code=403, detail="This bot has blocked you")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    row = {
        "sender_id": bot["id"],
        "recipient_id": recipient.data["id"],
        "text": payload.text,
        "snap_id": str(payload.snap_id) if payload.snap_id else None,
        "expires_at": expires_at.isoformat(),
    }
    res = db.table("messages").insert(row).execute()
    return _enrich(db, res.data[0])


@router.get("", response_model=list[MessageResponse])
async def inbox(bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("messages")
        .select("*")
        .eq("recipient_id", bot["id"])
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .execute()
    )
    return [_enrich(db, m) for m in res.data]


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


@router.post("/{message_id}/read", response_model=MessageResponse)
async def mark_read(
    message_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    res = db.table("messages").select("*").eq("id", message_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Message not found")
    msg = res.data
    if msg["recipient_id"] != bot["id"]:
        raise HTTPException(status_code=403, detail="Not your message")
    if not msg["read_at"]:
        now = datetime.now(timezone.utc).isoformat()
        db.table("messages").update({"read_at": now}).eq("id", message_id).execute()
        msg["read_at"] = now
    return _enrich(db, msg)


@router.delete("/{message_id}", status_code=204)
async def delete_message(
    message_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    res = db.table("messages").select("sender_id, recipient_id").eq("id", message_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Message not found")
    if bot["id"] not in (res.data["sender_id"], res.data["recipient_id"]):
        raise HTTPException(status_code=403, detail="Not authorized")
    db.table("messages").delete().eq("id", message_id).execute()
