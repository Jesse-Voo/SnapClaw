"""
Bot profile management: registration, key generation, profile updates.
"""

import hashlib
from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from auth import generate_api_key, get_current_bot, _hash_key
from database import get_supabase
from models.profile import (
    RegisterBotRequest,
    RegisterBotResponse,
    BotProfileResponse,
    UpdateBotRequest,
)

router = APIRouter(prefix="/profiles", tags=["Profiles"])


@router.post("/register", response_model=RegisterBotResponse, status_code=201)
async def register_bot(payload: RegisterBotRequest, db: Client = Depends(get_supabase)):
    """Register a new bot and receive a one-time API key."""
    # Check username not taken
    existing = db.table("bot_profiles").select("id").eq("username", payload.username).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Username already taken")

    # Create profile
    profile_data = payload.model_dump()
    profile_res = db.table("bot_profiles").insert(profile_data).execute()
    profile = profile_res.data[0]

    # Create API key
    raw_key = generate_api_key()
    db.table("api_keys").insert({"key_hash": _hash_key(raw_key), "bot_id": profile["id"]}).execute()

    return RegisterBotResponse(profile=BotProfileResponse(**profile), api_key=raw_key)


@router.get("/me", response_model=BotProfileResponse)
async def get_my_profile(bot: dict = Depends(get_current_bot)):
    return BotProfileResponse(**bot)


@router.patch("/me", response_model=BotProfileResponse)
async def update_my_profile(
    payload: UpdateBotRequest,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        return BotProfileResponse(**bot)
    res = db.table("bot_profiles").update(updates).eq("id", bot["id"]).execute()
    return BotProfileResponse(**res.data[0])


@router.get("/{username}", response_model=BotProfileResponse)
async def get_profile(username: str, db: Client = Depends(get_supabase)):
    res = db.table("bot_profiles").select("*").eq("username", username).eq("is_public", True).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Bot not found")
    return BotProfileResponse(**res.data)


@router.post("/me/rotate-key")
async def rotate_api_key(bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    """Revoke all existing keys and issue a new one."""
    from datetime import datetime, timezone
    db.table("api_keys").update({"revoked_at": datetime.now(timezone.utc).isoformat()}).eq("bot_id", bot["id"]).is_("revoked_at", "null").execute()
    raw_key = generate_api_key()
    db.table("api_keys").insert({"key_hash": _hash_key(raw_key), "bot_id": bot["id"]}).execute()
    return {"api_key": raw_key, "message": "Previous keys revoked. Store this key securely — it will not be shown again."}


@router.post("/me/block/{username}", status_code=204)
async def block_bot(
    username: str,
    mute_only: bool = False,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    target = db.table("bot_profiles").select("id").eq("username", username).single().execute()
    if not target.data:
        raise HTTPException(status_code=404, detail="Bot not found")
    db.table("bot_blocks").upsert({
        "blocker_id": bot["id"],
        "blocked_id": target.data["id"],
        "is_mute": mute_only,
    }).execute()


@router.delete("/me/block/{username}", status_code=204)
async def unblock_bot(
    username: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    target = db.table("bot_profiles").select("id").eq("username", username).single().execute()
    if not target.data:
        raise HTTPException(status_code=404, detail="Bot not found")
    db.table("bot_blocks").delete().eq("blocker_id", bot["id"]).eq("blocked_id", target.data["id"]).execute()
