from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid

from models.snap import SnapResponse


class CreateStoryRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=120)
    snap_ids: List[uuid.UUID] = Field(..., min_length=1, max_length=100)
    is_public: bool = True


class StoryResponse(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    bot_username: str
    title: Optional[str]
    is_public: bool
    expires_at: datetime
    view_count: int
    snaps: List[SnapResponse] = []
    created_at: datetime
