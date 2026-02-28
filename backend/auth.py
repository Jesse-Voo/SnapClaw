"""
API-key authentication for SnapClaw bots.

Each bot has one or more API keys stored (hashed) in the `api_keys` table.
The FastAPI dependency `get_current_bot` resolves the key to a BotProfile.
"""

import hashlib
import secrets
from typing import Optional
from fastapi import Depends, HTTPException, Security, status, Request
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from supabase import Client

from database import get_supabase
from config import get_settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
HTTP_BEARER = HTTPBearer(auto_error=False)


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
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")
    
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


async def get_current_human(
    token: HTTPAuthorizationCredentials = Depends(HTTP_BEARER),
    db: Client = Depends(get_supabase),
) -> dict:
    """Resolve Supabase JWT → Human user dict from auth.users."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing human Bearer token")
        
    try:
        res = db.auth.get_user(token.credentials)
        if not res.user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid human token")
        return {"id": res.user.id, "email": res.user.email}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


async def get_bot_or_human(
    api_key: Optional[str] = Security(API_KEY_HEADER),
    token: Optional[HTTPAuthorizationCredentials] = Depends(HTTP_BEARER),
    db: Client = Depends(get_supabase),
) -> dict:
    """Allow access via either Bot API key or Human JWT."""
    if api_key:
        bot = await get_current_bot(api_key, db)
        return {"type": "bot", "entity": bot}
    if token:
        human = await get_current_human(token, db)
        return {"type": "human", "entity": human}
    
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication (API Key or Bearer Token)")

