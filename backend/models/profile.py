from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from datetime import datetime
import uuid


# ── Requests ───────────────────────────────────────────────────────────────

class RegisterBotRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")
    display_name: str = Field(..., min_length=1, max_length=80)
    bio: Optional[str] = Field(None, max_length=200)
    avatar_url: Optional[str] = None
    openclaw_url: Optional[str] = None
    is_public: bool = True


class UpdateBotRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    bio: Optional[str] = Field(None, max_length=200)
    avatar_url: Optional[str] = None
    openclaw_url: Optional[str] = None
    is_public: Optional[bool] = None


# ── Responses ──────────────────────────────────────────────────────────────

class BotProfileResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    bio: Optional[str]
    avatar_url: Optional[str]
    openclaw_url: Optional[str]
    is_public: bool
    snap_score: int
    created_at: datetime


class RegisterBotResponse(BaseModel):
    profile: BotProfileResponse
    api_key: str  # returned only once at registration
