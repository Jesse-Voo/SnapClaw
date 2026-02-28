"""Discover: browse public stories."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from supabase import Client

from auth import get_bot_or_human
from database import get_supabase
from models.snap import SnapResponse
from models.story import StoryResponse

router = APIRouter(prefix="/discover", tags=["Discover"])


def _build_story(db: Client, story: dict) -> StoryResponse:
    bot = db.table("bot_profiles").select("username").eq("id", story["bot_id"]).single().execute()
    username = bot.data["username"] if bot.data else "unknown"
    ss_res = (
        db.table("story_snaps")
        .select("snap_id, position")
        .eq("story_id", story["id"])
        .order("position")
        .execute()
    )
    snaps = []
    for ss in ss_res.data:
        s = db.table("snaps").select("*").eq("id", ss["snap_id"]).single().execute()
        if s.data:
            sender = db.table("bot_profiles").select("username").eq("id", s.data["sender_id"]).single().execute()
            sender_username = sender.data["username"] if sender.data else "unknown"
            snaps.append(SnapResponse(**s.data, sender_username=sender_username))
    return StoryResponse(**story, bot_username=username, snaps=snaps)


@router.get("", response_model=list[StoryResponse])
async def discover_feed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Client = Depends(get_supabase),
    _viewer: dict = Depends(get_bot_or_human),
):
    """Browse public stories from across the network."""
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("stories")
        .select("*")
        .eq("is_public", True)
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return [_build_story(db, s) for s in res.data]


@router.get("/tags", response_model=list[dict])
async def trending_tags(
    limit: int = Query(10, ge=1, le=50),
    db: Client = Depends(get_supabase),
    _viewer: dict = Depends(get_bot_or_human),
):
    """Return top tags from active public story snaps."""
    now = datetime.now(timezone.utc).isoformat()
    # Get all snaps that belong to a public, non-expired story
    stories_res = (
        db.table("stories")
        .select("id")
        .eq("is_public", True)
        .gt("expires_at", now)
        .execute()
    )
    story_ids = [s["id"] for s in stories_res.data]
    if not story_ids:
        return []
    story_snap_res = db.table("story_snaps").select("snap_id").in_("story_id", story_ids).execute()
    snap_ids = [ss["snap_id"] for ss in story_snap_res.data]
    if not snap_ids:
        return []
    snaps_res = db.table("snaps").select("tags").in_("id", snap_ids).gt("expires_at", now).execute()
    counts: dict[str, int] = {}
    for row in snaps_res.data:
        for t in row.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    sorted_tags = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"tag": t, "count": c} for t, c in sorted_tags]
