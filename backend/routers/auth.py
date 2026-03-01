"""
Custom username + password authentication for human users.
No email required — avoids Supabase email rate limits entirely.
JWTs are issued by SnapClaw, verified locally (no Supabase auth call per request).
"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import jwt
from supabase import Client

from database import get_supabase
from config import get_settings
from limiter import limiter

router = APIRouter(prefix="/auth", tags=["Auth"])
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── helpers ───────────────────────────────────────────────────────────────

def _issue_jwt(user_id: str, username: str) -> str:
    settings = get_settings()
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


# ── schemas ───────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    username: str
    password: str


class MigrateRequest(BaseModel):
    email: str
    old_password: str
    username: str
    password: str

# ── endpoints ─────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
@limiter.limit("5/hour")
async def register(
    request: Request,
    payload: AuthRequest,
    db: Client = Depends(get_supabase),
):
    """Register a new human account with username + password. One account per IP."""
    username = payload.username.strip().lower()

    if len(username) < 3 or len(username) > 30:
        raise HTTPException(400, "Username must be 3-30 characters")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    if not all(c in allowed for c in username):
        raise HTTPException(400, "Username may only contain letters, numbers, _ and -")
    if len(payload.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    ip = _get_ip(request)
    if ip not in ("127.0.0.1", "::1", "unknown"):
        try:
            existing_ip = db.table("human_users").select("id").eq("ip_address", ip).execute()
            if existing_ip.data:
                raise HTTPException(400, "An account already exists from this IP address")
        except HTTPException:
            raise
        except Exception:
            pass

    existing = db.table("human_users").select("id").eq("username", username).execute()
    if existing.data:
        raise HTTPException(400, "Username already taken")

    pw_hash = _pwd.hash(payload.password)
    try:
        res = db.table("human_users").insert({
            "username": username,
            "password_hash": pw_hash,
            "ip_address": ip,
        }).execute()
    except Exception as exc:
        raise HTTPException(500, f"Registration failed: {exc}")

    user = res.data[0]
    token = _issue_jwt(user["id"], user["username"])
    return {"token": token, "username": user["username"], "id": user["id"]}


@router.post("/login")
@limiter.limit("20/minute")
async def login(
    request: Request,
    payload: AuthRequest,
    db: Client = Depends(get_supabase),
):
    """Log in with username + password. Returns a JWT."""
    username = payload.username.strip().lower()

    res = db.table("human_users").select("*").eq("username", username).execute()
    if not res.data:
        raise HTTPException(401, "Invalid username or password")

    user = res.data[0]
    if not _pwd.verify(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid username or password")

    token = _issue_jwt(user["id"], user["username"])
    return {"token": token, "username": user["username"], "id": user["id"]}


@router.post("/migrate", status_code=201)
@limiter.limit("5/hour")
async def migrate_from_supabase(
    request: Request,
    payload: MigrateRequest,
    db: Client = Depends(get_supabase),
):
    """
    Migrate an old Supabase email account to the new username+password system.
    Verifies email+password directly on the server.
    Bot ownership is preserved by reusing the same UUID as the primary key.
    """
    from supabase import create_client
    settings = get_settings()

    # Sign in with old email+password using anon key (not service role)
    try:
        anon_client = create_client(settings.supabase_url, settings.supabase_anon_key)
        sign_in = anon_client.auth.sign_in_with_password({
            "email": payload.email.strip().lower(),
            "password": payload.old_password,
        })
        if not sign_in.user:
            raise HTTPException(401, "Could not verify old email account - check email and password")
        supabase_id = sign_in.user.id
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, f"Old account verification failed: {exc}")

    username = payload.username.strip().lower()
    if len(username) < 3 or len(username) > 30:
        raise HTTPException(400, "Username must be 3-30 characters")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    if not all(c in allowed for c in username):
        raise HTTPException(400, "Username may only contain letters, numbers, _ and -")
    if len(payload.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    # Already migrated? Issue a fresh token.
    try:
        already = db.table("human_users").select("id, username").eq("id", supabase_id).execute()
        if already.data:
            user = already.data[0]
            token = _issue_jwt(user["id"], user["username"])
            return {"token": token, "username": user["username"], "id": user["id"], "migrated": False}
    except Exception:
        pass

    # Check new username not taken
    name_taken = db.table("human_users").select("id").eq("username", username).execute()
    if name_taken.data:
        raise HTTPException(400, "Username already taken - choose another")

    pw_hash = _pwd.hash(payload.password)
    ip = _get_ip(request)
    try:
        res = db.table("human_users").insert({
            "id": supabase_id,
            "username": username,
            "password_hash": pw_hash,
            "ip_address": ip,
        }).execute()
    except Exception as exc:
        raise HTTPException(500, f"Migration failed: {exc}")

    user = res.data[0]
    token = _issue_jwt(user["id"], user["username"])
    return {"token": token, "username": user["username"], "id": user["id"], "migrated": True}
