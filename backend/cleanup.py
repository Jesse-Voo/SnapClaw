"""
Background cleanup: delete expired snaps, stories, and messages from Supabase.
Also purges associated Supabase Storage files to stay within the free plan.
Runs on a configurable interval via APScheduler.
"""

import logging
from datetime import datetime, timezone

from supabase import Client

from config import get_settings

logger = logging.getLogger("snapclaw.cleanup")


def _purge_storage_files(db: Client, image_urls: list) -> int:
    """Delete storage objects for a list of image_urls. Returns count deleted."""
    settings = get_settings()
    bucket = settings.supabase_storage_bucket
    marker = "/object/public/" + bucket + "/"
    paths = []
    for url in image_urls:
        if not url:
            continue
        idx = url.find(marker)
        if idx != -1:
            paths.append(url[idx + len(marker):])
    if not paths:
        return 0
    try:
        db.storage.from_(bucket).remove(paths)
        return len(paths)
    except Exception as exc:
        logger.warning("Storage purge failed: %s", exc)
        return 0


def run_cleanup(db: Client) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    stats = {}

    # ── Expired snaps: delete storage files first, then DB rows ──────────
    expired_snaps = db.table("snaps").select("id, image_url").lt("expires_at", now).execute()
    if expired_snaps.data:
        urls = [row["image_url"] for row in expired_snaps.data]
        stats["storage_files_deleted"] = _purge_storage_files(db, urls)
        snap_ids = [row["id"] for row in expired_snaps.data]
        db.table("snaps").delete().in_("id", snap_ids).execute()
        stats["snaps_deleted"] = len(snap_ids)
    else:
        stats["snaps_deleted"] = 0

    # ── Expired stories: cascade deletes story_snaps join rows ────────────
    # (snaps themselves are deleted above by their own expires_at)
    stories_res = db.table("stories").delete().lt("expires_at", now).execute()
    stats["stories_deleted"] = len(stories_res.data) if stories_res.data else 0

    # ── Expired messages ─────────────────────────────────────────────────
    messages_res = db.table("messages").delete().lt("expires_at", now).execute()
    stats["messages_deleted"] = len(messages_res.data) if messages_res.data else 0

    # ── Streak maintenance ────────────────────────────────────────────────
    from datetime import timedelta
    risk_threshold = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    db.table("streaks").update({"at_risk": True}).lt("last_snap_at", risk_threshold).eq("at_risk", False).execute()

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
    else:
        logger.debug("Cleanup run: nothing to purge")
    return stats
