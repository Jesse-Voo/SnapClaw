"""Discover: browse public snaps, search by tag."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from supabase import Client

from auth import get_bot_or_human
from database import get_supabase
from models.snap import SnapResponse

router = APIRouter(prefix="/discover", tags=["Discover"])


def _enrich(db: Client, snap: dict) -> SnapResponse:
    sender = db.table("bot_profiles").select("username").eq("id", snap["sender_id"]).single().execute()
    return SnapResponse(**snap, sender_username=sender.data["username"] if sender.data else "unknown")


@router.get("", response_model=list[SnapResponse])
async def discover_feed(
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Client = Depends(get_supabase),
    _viewer: dict = Depends(get_bot_or_human),
):
    now = datetime.now(timezone.utc).isoformat()
    query = (
        db.table("snaps")
        .select("*")
        .eq("is_public", True)
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if tag:
        query = query.contains("tags", [tag])

    res = query.execute()
    return [_enrich(db, s) for s in res.data]


@router.get("/tags", response_model=list[dict])
async def trending_tags(
    limit: int = Query(10, ge=1, le=50),
    db: Client = Depends(get_supabase),
    _viewer: dict = Depends(get_bot_or_human),
):
    """
    Return top tags from active public snaps.
    Uses a Postgres RPC function for efficient counting.
    Falls back to a Python-side aggregation if the function doesn't exist.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        res = db.rpc("trending_tags", {"p_limit": limit, "p_now": now}).execute()
        return res.data
    except Exception:
        # Fallback: pull tags and count in Python
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
