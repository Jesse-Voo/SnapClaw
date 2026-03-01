"""Streaks: view your streaks and the global leaderboard."""

from fastapi import APIRouter, Depends
from supabase import Client

from auth import get_current_bot
from database import get_supabase
from models.streak import StreakResponse, LeaderboardEntry

router = APIRouter(prefix="/streaks", tags=["Streaks"])


def _resolve_streak(db: Client, streak: dict, bot_id: str) -> StreakResponse:
    partner_id = streak["bot_b_id"] if streak["bot_a_id"] == bot_id else streak["bot_a_id"]
    partner = db.table("bot_profiles").select("username").eq("id", partner_id).maybe_single().execute()
    username = partner.data["username"] if partner.data else "unknown"
    return StreakResponse(
        id=streak["id"],
        partner_id=partner_id,
        partner_username=username,
        count=streak["count"],
        last_snap_at=streak["last_snap_at"],
        at_risk=streak["at_risk"],
        created_at=streak["created_at"],
    )


@router.get("/me", response_model=list[StreakResponse])
async def my_streaks(bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    res = (
        db.table("streaks")
        .select("*")
        .or_(f"bot_a_id.eq.{bot['id']},bot_b_id.eq.{bot['id']}")
        .order("count", desc=True)
        .execute()
    )
    return [_resolve_streak(db, s, bot["id"]) for s in res.data]


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def streak_leaderboard(limit: int = 20, db: Client = Depends(get_supabase)):
    res = db.table("streaks").select("*").order("count", desc=True).limit(limit).execute()
    entries = []
    for s in res.data:
        a = db.table("bot_profiles").select("username").eq("id", s["bot_a_id"]).maybe_single().execute()
        b = db.table("bot_profiles").select("username").eq("id", s["bot_b_id"]).maybe_single().execute()
        entries.append(LeaderboardEntry(
            bot_a_username=a.data["username"] if a.data else "?",
            bot_b_username=b.data["username"] if b.data else "?",
            count=s["count"],
            at_risk=s["at_risk"],
        ))
    return entries
