from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid


class SendMessageRequest(BaseModel):
    recipient_username: str
    text: Optional[str] = Field(None, max_length=2000)
    snap_id: Optional[uuid.UUID] = None
    expires_in_hours: int = Field(default=24, ge=1, le=168)


class MessageResponse(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    sender_username: str
    recipient_id: uuid.UUID
    snap_id: Optional[uuid.UUID]
    text: Optional[str]
    read_at: Optional[datetime]
    expires_at: datetime
    created_at: datetime
