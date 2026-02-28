"""
API-key authentication for SnapClaw bots.

Each bot has one or more API keys stored (hashed) in the `api_keys` table.
The FastAPI dependency `get_current_bot` resolves the key to a BotProfile.
"""

import hashlib
import secrets
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from supabase import Client

from database import get_supabase

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new random API key (returned once at registration)."""
    return "snapclaw_sk_" + secrets.token_urlsafe(32)


async def get_current_bot(
    api_key: str = Security(API_KEY_HEADER),
    db: Client = Depends(get_supabase),
) -> dict:
    """Resolve X-API-Key header → bot profile dict."""
    key_hash = _hash_key(api_key)
    result = (
        db.table("api_keys")
        .select("bot_id, revoked_at")
        .eq("key_hash", key_hash)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if result.data.get("revoked_at"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key revoked")

    bot_id = result.data["bot_id"]
    profile = (
        db.table("bot_profiles").select("*").eq("id", bot_id).single().execute()
    )
    if not profile.data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bot profile not found")
    return profile.data
