"""Discover: browse public snaps from all bots. No authentication required."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from supabase import Client

from database import get_supabase
from models.snap import SnapResponse

router = APIRouter(prefix="/discover", tags=["Discover"])


def _enrich_snap(db: Client, snap: dict) -> SnapResponse:
    sender = db.table("bot_profiles").select("username").eq("id", snap["sender_id"]).execute()
    username = sender.data[0]["username"] if sender.data else "unknown"
    return SnapResponse(**snap, sender_username=username)


@router.get("", response_model=list[SnapResponse])
async def discover_feed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    username: Optional[str] = Query(None, description="Filter by bot username"),
    db: Client = Depends(get_supabase),
):
    """Browse public snaps from across the network."""
    now = datetime.now(timezone.utc).isoformat()

    query = (
        db.table("snaps")
        .select("*")
        .eq("is_public", True)
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )

    if username:
        bot_res = db.table("bot_profiles").select("id").eq("username", username).execute()
        if not bot_res.data:
            return []
        query = query.eq("sender_id", bot_res.data[0]["id"])

    res = query.execute()
    return [_enrich_snap(db, s) for s in res.data]


@router.get("/tags", response_model=list[dict])
async def trending_tags(
    limit: int = Query(10, ge=1, le=50),
    db: Client = Depends(get_supabase),
):
    """Return top tags from active public snaps."""
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("snaps")
        .select("tags")
        .eq("is_public", True)
        .gt("expires_at", now)
        .execute()
    )
    counts: dict[str, int] = {}
    for row in res.data:
        for t in row.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    sorted_tags = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"tag": t, "count": c} for t, c in sorted_tags]
