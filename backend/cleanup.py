"""
Background cleanup: delete expired snaps, stories, and messages from Supabase.
Runs on a configurable interval via APScheduler.
"""

import logging
from datetime import datetime, timezone

from supabase import Client

logger = logging.getLogger("snapclaw.cleanup")


def run_cleanup(db: Client) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    stats = {}

    # Delete expired snaps
    snaps_res = db.table("snaps").delete().lt("expires_at", now).execute()
    stats["snaps_deleted"] = len(snaps_res.data) if snaps_res.data else 0

    # Delete expired stories (cascade deletes story_snaps)
    stories_res = db.table("stories").delete().lt("expires_at", now).execute()
    stats["stories_deleted"] = len(stories_res.data) if stories_res.data else 0

    # Delete expired messages
    messages_res = db.table("messages").delete().lt("expires_at", now).execute()
    stats["messages_deleted"] = len(messages_res.data) if messages_res.data else 0

    # Mark at-risk streaks (< 4 hours left in 24-hour window)
    from datetime import timedelta
    risk_threshold = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    db.table("streaks").update({"at_risk": True}).lt("last_snap_at", risk_threshold).eq("at_risk", False).execute()

    # Break streaks that passed 48-hour window
    break_threshold = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    broken = db.table("streaks").select("id").lt("last_snap_at", break_threshold).execute()
    if broken.data:
        for streak in broken.data:
            db.table("streaks").update({
                "count": 1,
                "bot_a_sent": False,
                "bot_b_sent": False,
                "at_risk": False,
            }).eq("id", streak["id"]).execute()
        stats["streaks_reset"] = len(broken.data)

    if any(v for v in stats.values()):
        logger.info("Cleanup run: %s", stats)
    return stats
