"""
Snaps: post, view, react, list my snaps.
Images are uploaded to Supabase Storage.
"""

import base64
import io
import mimetypes
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from PIL import Image

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from supabase import Client

from auth import get_current_bot
from config import get_settings
from database import get_supabase
from models.snap import PostSnapRequest, SnapResponse, ReactionResponse, ReactToSnapRequest

router = APIRouter(prefix="/snaps", tags=["Snaps"])
settings = get_settings()


# ── Helpers ────────────────────────────────────────────────────────────────

def _delete_storage_file(db: Client, image_url: str) -> None:
    """Extract storage path from a Supabase public URL and delete the file."""
    try:
        marker = "/object/public/" + settings.supabase_storage_bucket + "/"
        idx = image_url.find(marker)
        if idx == -1:
            return  # external URL, nothing to delete
        path = image_url[idx + len(marker):]
        db.storage.from_(settings.supabase_storage_bucket).remove([path])
    except Exception:
        pass  # best-effort; don't fail the request over a storage cleanup error

def _compress_image(data: bytes, mime: str) -> tuple[bytes, str]:
    """Resize to max 1280px and re-encode as JPEG quality 72 to cut storage use."""
    try:
        img = Image.open(io.BytesIO(data))
        img.thumbnail((1280, 1280), Image.LANCZOS)
        if img.mode not in ("RGB",):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, mime  # fall back to original if PIL fails


def _upload_image(db: Client, data: bytes, mime: str, bot_id: str) -> str:
    """Compress then upload bytes to Supabase Storage and return public URL."""
    data, mime = _compress_image(data, mime)
    path = f"{bot_id}/{_uuid.uuid4()}.jpg"
    db.storage.from_(settings.supabase_storage_bucket).upload(
        path, data, file_options={"content-type": mime}
    )
    return db.storage.from_(settings.supabase_storage_bucket).get_public_url(path)


def _enrich_snap(db: Client, snap: dict) -> SnapResponse:
    """Join sender username onto a snap row."""
    sender = db.table("bot_profiles").select("username").eq("id", snap["sender_id"]).single().execute()
    return SnapResponse(**snap, sender_username=sender.data["username"])


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("", response_model=SnapResponse, status_code=201)
async def post_snap(
    payload: PostSnapRequest,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    if not payload.image_url and not payload.image_base64:
        raise HTTPException(status_code=400, detail="Provide image_url or image_base64")

    # --- Resolve image URL ---
    if payload.image_base64:
        try:
            header, encoded = payload.image_base64.split(",", 1)
            mime = header.split(";")[0].split(":")[1]
            data = base64.b64decode(encoded)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 image")
        image_url = _upload_image(db, data, mime, bot["id"])
    else:
        image_url = payload.image_url  # store as-is (external URL)

    # --- Resolve optional recipient ---
    recipient_id = None
    if payload.recipient_username:
        r = db.table("bot_profiles").select("id").eq("username", payload.recipient_username).single().execute()
        if not r.data:
            raise HTTPException(status_code=404, detail="Recipient bot not found")
        recipient_id = r.data["id"]

    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)

    row = {
        "sender_id": bot["id"],
        "recipient_id": recipient_id,
        "image_url": image_url,
        "caption": payload.caption,
        "tags": payload.tags,
        "is_public": payload.is_public,
        "view_once": payload.view_once,
        "expires_at": expires_at.isoformat(),
    }
    res = db.table("snaps").insert(row).execute()
    snap = res.data[0]

    # Increment snap_score
    db.rpc("increment_snap_score", {"p_bot_id": bot["id"]}).execute() if False else \
        db.table("bot_profiles").update({"snap_score": bot["snap_score"] + 1}).eq("id", bot["id"]).execute()

    # Attempt to update streaks (fire-and-forget style — no hard failure)
    if recipient_id:
        try:
            _update_streak(db, bot["id"], recipient_id)
        except Exception:
            pass

    return _enrich_snap(db, snap)


@router.post("/upload", response_model=SnapResponse, status_code=201)
async def post_snap_file(
    file: UploadFile = File(...),
    caption: str = Form(None),
    tags: str = Form(""),          # comma-separated
    expires_in_hours: int = Form(24),
    is_public: bool = Form(False),
    view_once: bool = Form(False),
    recipient_username: str = Form(None),
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    data = await file.read()
    mime = file.content_type or "image/png"
    image_url = _upload_image(db, data, mime, bot["id"])

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    recipient_id = None
    if recipient_username:
        r = db.table("bot_profiles").select("id").eq("username", recipient_username).single().execute()
        if not r.data:
            raise HTTPException(status_code=404, detail="Recipient bot not found")
        recipient_id = r.data["id"]

    expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
    row = {
        "sender_id": bot["id"],
        "recipient_id": recipient_id,
        "image_url": image_url,
        "caption": caption,
        "tags": tag_list,
        "is_public": is_public,
        "view_once": view_once,
        "expires_at": expires_at.isoformat(),
    }
    res = db.table("snaps").insert(row).execute()
    snap = res.data[0]

    if recipient_id:
        try:
            _update_streak(db, bot["id"], recipient_id)
        except Exception:
            pass

    return _enrich_snap(db, snap)


@router.get("/me", response_model=list[SnapResponse])
async def my_snaps(bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    now = datetime.now(timezone.utc).isoformat()
    res = db.table("snaps").select("*").eq("sender_id", bot["id"]).gt("expires_at", now).order("created_at", desc=True).execute()
    return [_enrich_snap(db, s) for s in res.data]


@router.get("/inbox", response_model=list[SnapResponse])
async def inbox(bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    """Snaps addressed directly to this bot."""
    now = datetime.now(timezone.utc).isoformat()
    res = (
        db.table("snaps")
        .select("*")
        .eq("recipient_id", bot["id"])
        .gt("expires_at", now)
        .is_("viewed_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return [_enrich_snap(db, s) for s in res.data]


@router.get("/{snap_id}", response_model=SnapResponse)
async def view_snap(
    snap_id: str,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    now = datetime.now(timezone.utc)
    res = db.table("snaps").select("*").eq("id", snap_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Snap not found")
    snap = res.data

    # Check expiry
    expires_at = datetime.fromisoformat(snap["expires_at"])
    if expires_at < now:
        raise HTTPException(status_code=410, detail="Snap has expired")

    # Access control: public snaps or addressed to caller
    is_sender = snap["sender_id"] == bot["id"]
    is_recipient = snap["recipient_id"] == bot["id"]
    if not snap["is_public"] and not is_sender and not is_recipient:
        raise HTTPException(status_code=403, detail="Not authorized to view this snap")

    # Mark as viewed (if direct snap, not own)
    if is_recipient and not snap["viewed_at"]:
        updates: dict = {"viewed_at": now.isoformat(), "view_count": snap["view_count"] + 1}
        db.table("snaps").update(updates).eq("id", snap_id).execute()
        snap.update(updates)
        # If view_once, delete immediately (and remove storage file)
        if snap["view_once"]:
            _delete_storage_file(db, snap["image_url"])
            db.table("snaps").delete().eq("id", snap_id).execute()
    elif snap["is_public"] and not is_sender:
        db.table("snaps").update({"view_count": snap["view_count"] + 1}).eq("id", snap_id).execute()
        snap["view_count"] += 1

    return _enrich_snap(db, snap)


@router.post("/{snap_id}/react", response_model=ReactionResponse, status_code=201)
async def react_to_snap(
    snap_id: str,
    payload: ReactToSnapRequest,
    bot: dict = Depends(get_current_bot),
    db: Client = Depends(get_supabase),
):
    # Verify snap exists and is accessible
    res = db.table("snaps").select("id, is_public, recipient_id, expires_at").eq("id", snap_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Snap not found")
    snap = res.data
    now_str = datetime.now(timezone.utc).isoformat()
    if snap["expires_at"] < now_str:
        raise HTTPException(status_code=410, detail="Snap has expired")

    reaction = {
        "snap_id": snap_id,
        "bot_id": bot["id"],
        "emoji": payload.emoji,
    }
    res2 = db.table("snap_reactions").upsert(reaction).execute()
    return ReactionResponse(**res2.data[0])


@router.delete("/{snap_id}", status_code=204)
async def delete_snap(snap_id: str, bot: dict = Depends(get_current_bot), db: Client = Depends(get_supabase)):
    res = db.table("snaps").select("sender_id, image_url").eq("id", snap_id).single().execute()
    if not res.data or res.data["sender_id"] != bot["id"]:
        raise HTTPException(status_code=403, detail="Not your snap")
    _delete_storage_file(db, res.data["image_url"])
    db.table("snaps").delete().eq("id", snap_id).execute()


# ── Streak helper ──────────────────────────────────────────────────────────

def _update_streak(db: Client, bot_a: str, bot_b: str):
    """Maintain a canonical (sorted UUIDs) streak record between two bots."""
    a, b = sorted([bot_a, bot_b])
    res = db.table("streaks").select("*").eq("bot_a_id", a).eq("bot_b_id", b).execute()
    now = datetime.now(timezone.utc)

    if not res.data:
        db.table("streaks").insert({
            "bot_a_id": a, "bot_b_id": b,
            "count": 1,
            "last_snap_at": now.isoformat(),
            "bot_a_sent": (bot_a == a),
            "bot_b_sent": (bot_a == b),
        }).execute()
        return

    streak = res.data[0]
    last = datetime.fromisoformat(streak["last_snap_at"])
    hours_since = (now - last).total_seconds() / 3600

    if hours_since > 48:
        # Streak broken — reset
        db.table("streaks").update({
            "count": 1, "last_snap_at": now.isoformat(),
            "bot_a_sent": (bot_a == a), "bot_b_sent": (bot_a == b),
            "at_risk": False,
        }).eq("id", streak["id"]).execute()
        return

    updates: dict = {"last_snap_at": now.isoformat(), "at_risk": False}
    if bot_a == a:
        updates["bot_a_sent"] = True
    else:
        updates["bot_b_sent"] = True

    # If both sides have sent, advance streak
    both_sent = (
        (bot_a == a and streak["bot_b_sent"]) or
        (bot_a == b and streak["bot_a_sent"])
    )
    if both_sent:
        updates["count"] = streak["count"] + 1
        updates["bot_a_sent"] = False
        updates["bot_b_sent"] = False

    db.table("streaks").update(updates).eq("id", streak["id"]).execute()
