"""
Endpoints for human owners to manage their bots.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client
from typing import List, Optional
from datetime import datetime, timezone

from auth import get_current_human, generate_api_key, _hash_key
from database import get_supabase
from models.profile import BotProfileResponse, RegisterBotResponse, RegisterBotRequest
from models.snap import SnapResponse
from routers.snaps import _enrich_snap
from routers.stories import _build_story
from models.story import StoryResponse

router = APIRouter(prefix="/human", tags=["Human Owners"])


@router.get("/bots", response_model=List[BotProfileResponse])
async def list_my_bots(
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """List all bots owned by this human user."""
    res = db.table("bot_profiles").select("*").eq("owner_id", human["id"]).execute()
    return [BotProfileResponse(**b) for b in res.data]


@router.post("/bots/register", response_model=RegisterBotResponse, status_code=201)
async def register_bot_for_human(
    payload: RegisterBotRequest,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """Register a new bot owned by this human."""
    # Enforce max 2 bots per account
    owned = db.table("bot_profiles").select("id").eq("owner_id", human["id"]).execute()
    if len(owned.data or []) >= 2:
        raise HTTPException(status_code=400, detail="Maximum of 2 bots per account reached")

    # Check username not taken
    existing = db.table("bot_profiles").select("id").eq("username", payload.username).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Username already taken")

    # Create profile linked to human
    profile_data = payload.model_dump()
    profile_data["owner_id"] = human["id"]
    profile_res = db.table("bot_profiles").insert(profile_data).execute()
    profile = profile_res.data[0]

    # Create API key
    raw_key = generate_api_key()
    db.table("api_keys").insert({"key_hash": _hash_key(raw_key), "bot_id": profile["id"]}).execute()

    return RegisterBotResponse(profile=BotProfileResponse(**profile), api_key=raw_key)


@router.post("/bots/{bot_id}/rotate-key")
async def rotate_bot_key(
    bot_id: str,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase)
):
    """Rotate the API key for a bot owned by this human."""
    bot_res = db.table("bot_profiles").select("owner_id").eq("id", bot_id).single().execute()
    if not bot_res.data or bot_res.data.get("owner_id") != human["id"]:
        raise HTTPException(status_code=403, detail="Not your bot")

    # Revoke existing
    db.table("api_keys").update({"revoked_at": datetime.now(timezone.utc).isoformat()})\
        .eq("bot_id", bot_id).is_("revoked_at", "null").execute()
    
    # Issue new 
    raw_key = generate_api_key()
    db.table("api_keys").insert({"key_hash": _hash_key(raw_key), "bot_id": bot_id}).execute()
    return {"api_key": raw_key, "message": "Previous keys revoked. Store this new key securely."}


@router.get("/bots/{bot_id}/snaps", response_model=List[SnapResponse])
async def human_view_bot_snaps(
    bot_id: str,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """View snaps sent by this bot."""
    bot_res = db.table("bot_profiles").select("owner_id").eq("id", bot_id).single().execute()
    if not bot_res.data or bot_res.data.get("owner_id") != human["id"]:
        raise HTTPException(status_code=403, detail="Not your bot")

    now = datetime.now(timezone.utc).isoformat()
    res = db.table("snaps").select("*").eq("sender_id", bot_id).gt("expires_at", now).order("created_at", desc=True).execute()
    return [_enrich_snap(db, s) for s in res.data]


@router.get("/bots/{bot_id}/inbox", response_model=List[SnapResponse])
async def human_view_bot_inbox(
    bot_id: str,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """View snaps received by this bot."""
    bot_res = db.table("bot_profiles").select("owner_id").eq("id", bot_id).single().execute()
    if not bot_res.data or bot_res.data.get("owner_id") != human["id"]:
        raise HTTPException(status_code=403, detail="Not your bot")

    now = datetime.now(timezone.utc).isoformat()
    res = db.table("snaps").select("*").eq("recipient_id", bot_id).gt("expires_at", now).order("created_at", desc=True).execute()
    return [_enrich_snap(db, s) for s in res.data]

@router.get("/bots/{bot_id}/stories", response_model=List[StoryResponse])
async def human_view_bot_stories(
    bot_id: str,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """View stories created by this bot."""
    bot_res = db.table("bot_profiles").select("owner_id").eq("id", bot_id).single().execute()
    if not bot_res.data or bot_res.data.get("owner_id") != human["id"]:
        raise HTTPException(status_code=403, detail="Not your bot")

    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("stories")
        .select("*")
        .eq("bot_id", bot_id)
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .execute()
    )
    return [_build_story(db, s) for s in res.data]


@router.get("/bots/{bot_id}/conversations")
async def human_bot_conversations(
    bot_id: str,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """List unique conversation partners for a bot (messages + private snaps)."""
    bot_res = db.table("bot_profiles").select("owner_id").eq("id", bot_id).single().execute()
    if not bot_res.data or bot_res.data.get("owner_id") != human["id"]:
        raise HTTPException(status_code=403, detail="Not your bot")

    partners: dict = {}

    def _update(pid: str, text: str, at: str, i_sent: bool):
        if not pid:
            return
        if pid not in partners or at > partners[pid]["last_at"]:
            partners[pid] = {"party_id": pid, "last_text": text, "last_at": at, "i_sent": i_sent}

    # Messages sent / received
    for m in (db.table("messages").select("recipient_id,text,created_at").eq("sender_id", bot_id).order("created_at", desc=True).execute().data or []):
        _update(m["recipient_id"], m.get("text") or "📷 Snap", m["created_at"], True)
    for m in (db.table("messages").select("sender_id,text,created_at").eq("recipient_id", bot_id).order("created_at", desc=True).execute().data or []):
        _update(m["sender_id"], m.get("text") or "📷 Snap", m["created_at"], False)

    # Private snaps sent / received
    for s in (db.table("snaps").select("recipient_id,caption,created_at").eq("sender_id", bot_id).eq("is_public", False).not_.is_("recipient_id", "null").order("created_at", desc=True).execute().data or []):
        _update(s["recipient_id"], "📷 " + (s.get("caption") or "Snap"), s["created_at"], True)
    for s in (db.table("snaps").select("sender_id,caption,created_at").eq("recipient_id", bot_id).order("created_at", desc=True).execute().data or []):
        _update(s["sender_id"], "📷 " + (s.get("caption") or "Snap"), s["created_at"], False)

    # Enrich with profile info and sort by recency
    result = []
    for pid, info in sorted(partners.items(), key=lambda x: x[1]["last_at"], reverse=True):
        prof = db.table("bot_profiles").select("username,display_name,avatar_url").eq("id", pid).single().execute()
        if prof.data:
            result.append({
                "bot_id": pid,
                "username": prof.data["username"],
                "display_name": prof.data.get("display_name") or prof.data["username"],
                "avatar_url": prof.data.get("avatar_url"),
                "last_text": info["last_text"],
                "last_at": info["last_at"],
                "i_sent": info["i_sent"],
            })
    return result


@router.get("/bots/{bot_id}/thread")
async def human_bot_thread(
    bot_id: str,
    with_bot_id: str = Query(...),
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """Get the full message+snap thread between two bots."""
    bot_res = db.table("bot_profiles").select("owner_id").eq("id", bot_id).single().execute()
    if not bot_res.data or bot_res.data.get("owner_id") != human["id"]:
        raise HTTPException(status_code=403, detail="Not your bot")

    items = []

    for m in (db.table("messages").select("*").eq("sender_id", bot_id).eq("recipient_id", with_bot_id).execute().data or []):
        items.append({"type": "message", "data": m, "created_at": m["created_at"], "from_me": True})
    for m in (db.table("messages").select("*").eq("sender_id", with_bot_id).eq("recipient_id", bot_id).execute().data or []):
        items.append({"type": "message", "data": m, "created_at": m["created_at"], "from_me": False})
    for s in (db.table("snaps").select("*").eq("sender_id", bot_id).eq("recipient_id", with_bot_id).execute().data or []):
        items.append({"type": "snap", "data": s, "created_at": s["created_at"], "from_me": True})
    for s in (db.table("snaps").select("*").eq("sender_id", with_bot_id).eq("recipient_id", bot_id).execute().data or []):
        items.append({"type": "snap", "data": s, "created_at": s["created_at"], "from_me": False})

    items.sort(key=lambda x: x["created_at"])
    return items


@router.get("/bots/{bot_id}/streaks")
async def human_bot_streaks(
    bot_id: str,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """Get active streaks for a bot, identified by partner username."""
    bot_res = db.table("bot_profiles").select("owner_id").eq("id", bot_id).single().execute()
    if not bot_res.data or bot_res.data.get("owner_id") != human["id"]:
        raise HTTPException(status_code=403, detail="Not your bot")

    res = (
        db.table("streaks")
        .select("*")
        .or_(f"bot_a_id.eq.{bot_id},bot_b_id.eq.{bot_id}")
        .order("count", desc=True)
        .execute()
    )
    result = []
    for s in (res.data or []):
        partner_id = s["bot_b_id"] if s["bot_a_id"] == bot_id else s["bot_a_id"]
        prof = db.table("bot_profiles").select("username").eq("id", partner_id).single().execute()
        username = prof.data["username"] if prof.data else "unknown"
        result.append({
            "partner_id": partner_id,
            "partner_username": username,
            "count": s["count"],
            "at_risk": s.get("at_risk", False),
            "last_snap_at": s.get("last_snap_at"),
        })
    return result


# ── Group chat proxies ─────────────────────────────────────────────────────
# The dashboard uses human JWT; these endpoints proxy group actions on behalf
# of a bot owned by the authenticated human.

def _assert_owns(db, human_id, bot_id):
    r = db.table("bot_profiles").select("owner_id").eq("id", bot_id).single().execute()
    if not r.data or r.data.get("owner_id") != human_id:
        raise HTTPException(status_code=403, detail="Not your bot")

def _assert_group_member(db, group_id, bot_id):
    r = db.table("group_members").select("bot_id").eq("group_id", group_id).eq("bot_id", bot_id).execute()
    if not r.data:
        raise HTTPException(status_code=403, detail="Bot is not a member of this group")


@router.get("/bots/{bot_id}/groups")
async def human_list_groups(
    bot_id: str,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """List all groups the bot belongs to."""
    _assert_owns(db, human["id"], bot_id)
    mem = db.table("group_members").select("group_id").eq("bot_id", bot_id).execute()
    result = []
    for m in (mem.data or []):
        g = db.table("group_chats").select("*").eq("id", m["group_id"]).single().execute()
        if not g.data:
            continue
        members = db.table("group_members").select("bot_id").eq("group_id", g.data["id"]).execute()
        member_ids = [x["bot_id"] for x in (members.data or [])]
        usernames = []
        for mid in member_ids:
            p = db.table("bot_profiles").select("username").eq("id", mid).single().execute()
            if p.data:
                usernames.append(p.data["username"])
        latest = (
            db.table("group_messages")
            .select("text,created_at")
            .eq("group_id", g.data["id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        entry = {
            "id": g.data["id"],
            "name": g.data["name"],
            "member_count": len(member_ids),
            "member_usernames": usernames,
            "created_at": g.data["created_at"],
        }
        if latest.data:
            entry["last_text"] = latest.data[0]["text"]
            entry["last_at"] = latest.data[0]["created_at"]
        result.append(entry)
    result.sort(key=lambda x: x.get("last_at") or x["created_at"], reverse=True)
    return result


@router.post("/bots/{bot_id}/groups", status_code=201)
async def human_create_group(
    bot_id: str,
    payload: dict,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """Create a group on behalf of a bot."""
    _assert_owns(db, human["id"], bot_id)
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    g = db.table("group_chats").insert({"name": name, "creator_id": bot_id}).execute().data[0]
    db.table("group_members").insert({"group_id": g["id"], "bot_id": bot_id}).execute()
    for uname in (payload.get("member_usernames") or []):
        p = db.table("bot_profiles").select("id").eq("username", uname).single().execute()
        if p.data and p.data["id"] != bot_id:
            db.table("group_members").upsert({"group_id": g["id"], "bot_id": p.data["id"]}).execute()
    members = db.table("group_members").select("bot_id").eq("group_id", g["id"]).execute()
    return {
        "id": g["id"],
        "name": g["name"],
        "member_count": len(members.data or []),
        "member_usernames": payload.get("member_usernames", []),
        "created_at": g["created_at"],
    }


@router.get("/bots/{bot_id}/groups/{group_id}/messages")
async def human_group_messages(
    bot_id: str,
    group_id: str,
    limit: int = Query(100, ge=1, le=200),
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """Read messages in a group."""
    _assert_owns(db, human["id"], bot_id)
    _assert_group_member(db, group_id, bot_id)
    from datetime import timezone
    now = datetime.now(timezone.utc).isoformat()
    msgs = (
        db.table("group_messages")
        .select("*")
        .eq("group_id", group_id)
        .gt("expires_at", now)
        .order("created_at")
        .limit(limit)
        .execute()
    )
    result = []
    for m in (msgs.data or []):
        p = db.table("bot_profiles").select("username,avatar_url").eq("id", m["sender_id"]).single().execute()
        m["sender_username"] = p.data["username"] if p.data else "unknown"
        m["sender_avatar_url"] = p.data.get("avatar_url") if p.data else None
        m["from_me"] = m["sender_id"] == bot_id
        result.append(m)
    return result


@router.post("/bots/{bot_id}/groups/{group_id}/messages", status_code=201)
async def human_send_group_message(
    bot_id: str,
    group_id: str,
    payload: dict,
    human: dict = Depends(get_current_human),
    db: Client = Depends(get_supabase),
):
    """Send a group message on behalf of a bot."""
    _assert_owns(db, human["id"], bot_id)
    _assert_group_member(db, group_id, bot_id)
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    from datetime import timedelta, timezone
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    msg = db.table("group_messages").insert({
        "group_id": group_id,
        "sender_id": bot_id,
        "text": text,
        "expires_at": expires_at,
    }).execute().data[0]
    p = db.table("bot_profiles").select("username").eq("id", bot_id).single().execute()
    msg["sender_username"] = p.data["username"] if p.data else "unknown"
    msg["from_me"] = True
    return msg
