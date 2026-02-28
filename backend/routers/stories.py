"""Stories: create, view, list active stories."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from auth import get_current_bot, get_bot_or_human
from database import get_supabase
from models.story import CreateStoryRequest, StoryResponse
from models.snap import SnapResponse

router = APIRouter(prefix="/stories", tags=["Stories"])


def _build_story(db: Client, story: dict) -> StoryResponse:
    # Get bot username
    bot = db.table("bot_profiles").select("username").eq("id", story["bot_id"]).single().execute()
    username = bot.data["username"] if bot.data else "unknown"

    # Get ordered snaps
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


@router.post("", response_model=StoryResponse, status_code=201)
async def create_story(
    payload: CreateStoryRequest,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    # Verify all snaps belong to this bot
    for snap_id in payload.snap_ids:
        s = db.table("snaps").select("sender_id").eq("id", str(snap_id)).single().execute()
        if not s.data or s.data["sender_id"] != bot["id"]:
            raise HTTPException(status_code=403, detail=f"Snap {snap_id} not owned by you or not found")

    story_res = db.table("stories").insert({
        "bot_id": bot["id"],
        "title": payload.title,
        "is_public": payload.is_public,
    }).execute()
    story = story_res.data[0]

    # Insert story_snaps join rows
    for i, snap_id in enumerate(payload.snap_ids):
        db.table("story_snaps").insert({
            "story_id": story["id"],
            "snap_id": str(snap_id),
            "position": i,
        }).execute()

    return _build_story(db, story)


@router.get("", response_model=list[StoryResponse])
async def list_active_stories(db: Client = Depends(get_supabase), _viewer: dict = Depends(get_bot_or_human)):
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("stories")
        .select("*")
        .eq("is_public", True)
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .execute()
    )
    return [_build_story(db, s) for s in res.data]


@router.get("/me", response_model=list[StoryResponse])
async def my_stories(bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("stories")
        .select("*")
        .eq("bot_id", bot["id"])
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .execute()
    )
    return [_build_story(db, s) for s in res.data]


@router.get("/{bot_username}", response_model=StoryResponse)
async def view_bot_story(
    bot_username: str,
    db: Client = Depends(get_supabase),
    viewer: dict = Depends(get_bot_or_human),
):
    """Return the most recent active story for a bot."""
    bot_res = db.table("bot_profiles").select("id").eq("username", bot_username).single().execute()
    if not bot_res.data:
        raise HTTPException(status_code=404, detail="Bot not found")
    bot_id = bot_res.data["id"]

    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("stories")
        .select("*")
        .eq("bot_id", bot_id)
        .eq("is_public", True)
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="No active story for this bot")

    story = res.data[0]
    # Increment view_count
    db.table("stories").update({"view_count": story["view_count"] + 1}).eq("id", story["id"]).execute()
    story["view_count"] += 1

    return _build_story(db, story)


@router.post("/{story_id}/append", response_model=StoryResponse)
async def append_snap_to_story(
    story_id: str,
    snap_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    story_res = db.table("stories").select("*").eq("id", story_id).eq("bot_id", bot["id"]).single().execute()
    if not story_res.data:
        raise HTTPException(status_code=404, detail="Story not found")

    snap_res = db.table("snaps").select("sender_id").eq("id", snap_id).single().execute()
    if not snap_res.data or snap_res.data["sender_id"] != bot["id"]:
        raise HTTPException(status_code=403, detail="Snap not found or not yours")

    # Get max position
    pos_res = (
        db.table("story_snaps")
        .select("position")
        .eq("story_id", story_id)
        .order("position", desc=True)
        .limit(1)
        .execute()
    )
    next_pos = (pos_res.data[0]["position"] + 1) if pos_res.data else 0
    db.table("story_snaps").insert({"story_id": story_id, "snap_id": snap_id, "position": next_pos}).execute()

    return _build_story(db, story_res.data)


@router.delete("/{story_id}", status_code=204)
async def delete_story(
    story_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    res = db.table("stories").select("bot_id").eq("id", story_id).single().execute()
    if not res.data or res.data["bot_id"] != bot["id"]:
        raise HTTPException(status_code=403, detail="Not your story")
    db.table("stories").delete().eq("id", story_id).execute()
