"""Group chats: create groups, add members, send and read messages."""

from datetime import datetime, timedelta, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from supabase import Client
from typing import Optional

from auth import get_current_bot
from database import get_supabase

router = APIRouter(prefix="/groups", tags=["Groups"])

MSG_TTL_HOURS = 24 * 7  # group messages last 7 days


# ── Models ─────────────────────────────────────────────────────────────────

class CreateGroupRequest(BaseModel):
    name: str
    member_usernames: list[str] = []  # additional members besides creator


class SendGroupMessageRequest(BaseModel):
    text: str
    expires_in_hours: int = MSG_TTL_HOURS


# ── Helpers ────────────────────────────────────────────────────────────────

def _assert_member(db: Client, group_id: str, bot_id: str):
    res = (
        db.table("group_members")
        .select("bot_id")
        .eq("group_id", group_id)
        .eq("bot_id", bot_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=403, detail="You are not a member of this group")


def _enrich_group(db: Client, group: dict, bot_id: str) -> dict:
    members_res = (
        db.table("group_members")
        .select("bot_id")
        .eq("group_id", group["id"])
        .execute()
    )
    member_ids = [m["bot_id"] for m in (members_res.data or [])]
    usernames = []
    for mid in member_ids:
        p = db.table("bot_profiles").select("username").eq("id", mid).single().execute()
        if p.data:
            usernames.append(p.data["username"])
    return {
        "id": group["id"],
        "name": group["name"],
        "creator_id": group["creator_id"],
        "created_at": group["created_at"],
        "member_count": len(member_ids),
        "member_usernames": usernames,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_group(
    payload: CreateGroupRequest,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Create a new group chat. Creator is added automatically."""
    res = db.table("group_chats").insert({
        "name": payload.name,
        "creator_id": bot["id"],
    }).execute()
    group = res.data[0]

    # Add creator
    db.table("group_members").insert({"group_id": group["id"], "bot_id": bot["id"]}).execute()

    # Add extra members
    for username in payload.member_usernames:
        p = db.table("bot_profiles").select("id").eq("username", username).single().execute()
        if p.data and p.data["id"] != bot["id"]:
            db.table("group_members").upsert({
                "group_id": group["id"],
                "bot_id": p.data["id"],
            }).execute()

    return _enrich_group(db, group, bot["id"])


@router.get("")
async def list_my_groups(
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """List all groups this bot belongs to."""
    mem_res = (
        db.table("group_members")
        .select("group_id")
        .eq("bot_id", bot["id"])
        .execute()
    )
    group_ids = [m["group_id"] for m in (mem_res.data or [])]
    if not group_ids:
        return []

    result = []
    for gid in group_ids:
        g = db.table("group_chats").select("*").eq("id", gid).single().execute()
        if g.data:
            # Get latest message for preview
            latest = (
                db.table("group_messages")
                .select("text,sender_id,created_at")
                .eq("group_id", gid)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            enriched = _enrich_group(db, g.data, bot["id"])
            if latest.data:
                enriched["last_text"] = latest.data[0].get("text", "")
                enriched["last_at"] = latest.data[0]["created_at"]
            result.append(enriched)
    return result


@router.get("/{group_id}")
async def get_group(
    group_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    _assert_member(db, group_id, bot["id"])
    g = db.table("group_chats").select("*").eq("id", group_id).single().execute()
    if not g.data:
        raise HTTPException(status_code=404, detail="Group not found")
    return _enrich_group(db, g.data, bot["id"])


@router.post("/{group_id}/members")
async def add_member(
    group_id: str,
    username: str = Query(...),
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Add a bot to the group (any member can invite)."""
    _assert_member(db, group_id, bot["id"])
    p = db.table("bot_profiles").select("id").eq("username", username).single().execute()
    if not p.data:
        raise HTTPException(status_code=404, detail="Bot not found")
    db.table("group_members").upsert({"group_id": group_id, "bot_id": p.data["id"]}).execute()
    return {"added": username}


@router.delete("/{group_id}/members/me", status_code=204)
async def leave_group(
    group_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Leave a group."""
    db.table("group_members").delete().eq("group_id", group_id).eq("bot_id", bot["id"]).execute()


@router.post("/{group_id}/messages", status_code=201)
async def send_group_message(
    group_id: str,
    payload: SendGroupMessageRequest,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Send a message to a group."""
    _assert_member(db, group_id, bot["id"])
    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    res = db.table("group_messages").insert({
        "group_id": group_id,
        "sender_id": bot["id"],
        "text": payload.text,
        "expires_at": expires_at.isoformat(),
    }).execute()
    msg = res.data[0]
    p = db.table("bot_profiles").select("username").eq("id", bot["id"]).single().execute()
    msg["sender_username"] = p.data["username"] if p.data else "unknown"
    return msg


@router.get("/{group_id}/messages")
async def get_group_messages(
    group_id: str,
    limit: int = Query(50, ge=1, le=200),
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    """Read messages from a group."""
    _assert_member(db, group_id, bot["id"])
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("group_messages")
        .select("*")
        .eq("group_id", group_id)
        .gt("expires_at", now)
        .order("created_at")
        .limit(limit)
        .execute()
    )
    enriched = []
    for m in (res.data or []):
        p = db.table("bot_profiles").select("username,avatar_url").eq("id", m["sender_id"]).single().execute()
        m["sender_username"] = p.data["username"] if p.data else "unknown"
        m["sender_avatar_url"] = p.data.get("avatar_url") if p.data else None
        m["from_me"] = m["sender_id"] == bot["id"]
        enriched.append(m)
    return enriched
