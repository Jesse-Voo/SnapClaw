"""
Endpoints for human owners to manage their bots.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client
from typing import List
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
