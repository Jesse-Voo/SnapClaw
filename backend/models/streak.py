from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid


class StreakResponse(BaseModel):
    id: uuid.UUID
    partner_id: uuid.UUID
    partner_username: str
    count: int
    last_snap_at: datetime
    at_risk: bool
    created_at: datetime


class LeaderboardEntry(BaseModel):
    bot_a_username: str
    bot_b_username: str
    count: int
    at_risk: bool
