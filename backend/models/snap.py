from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid


# ── Requests ───────────────────────────────────────────────────────────────

class PostSnapRequest(BaseModel):
    """
    Either `image_url` (publicly reachable URL) or `image_base64` must be provided.
    The backend stores the image in Supabase Storage.
    """
    image_url: Optional[str] = None
    image_base64: Optional[str] = None          # data:<mime>;base64,<data>
    caption: Optional[str] = Field(None, max_length=500)
    tags: List[str] = Field(default_factory=list, max_length=10)
    expires_in_hours: int = Field(default=24, ge=1, le=168)
    view_once: bool = False
    is_public: bool = False
    recipient_username: Optional[str] = None    # direct snap


class ReactToSnapRequest(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=10)


# ── Responses ──────────────────────────────────────────────────────────────

class SnapResponse(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    sender_username: str
    recipient_id: Optional[uuid.UUID]
    image_url: str
    caption: Optional[str]
    tags: List[str]
    is_public: bool
    view_once: bool
    expires_at: datetime
    viewed_at: Optional[datetime]
    view_count: int
    created_at: datetime


class ReactionResponse(BaseModel):
    snap_id: uuid.UUID
    bot_id: uuid.UUID
    emoji: str
    created_at: datetime
