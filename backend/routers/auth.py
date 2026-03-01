"""
Custom username + password authentication for human users.
No email required — avoids Supabase email rate limits entirely.
JWTs are issued by SnapClaw, verified locally (no Supabase auth call per request).
"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
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
    supabase_token: str
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
        raise HTTPException(400, "Username must be 3–30 characters")
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
    """Migrate an old Supabase email account to the new username+password system.
    Pass the Supabase JWT (obtained by logging in via Supabase on the client),
    choose a new username and password. Bot ownership is preserved.
    """
    # Verify old Supabase JWT
    try:
        user_res = db.auth.get_user(payload.supabase_token)
        if not user_res.user:
            raise HTTPException(401, "Could not verify old Supabase session")
        supabase_id = user_res.user.id
        supabase_email = user_res.user.email or ""
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, f"Invalid Supabase token: {exc}")

    username = payload.username.strip().lower()
    if len(username) < 3 or len(username) > 30:
        raise HTTPException(400, "Username must be 3–30 characters")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    if not all(c in allowed for c in username):
        raise HTTPException(400, "Username may only contain letters, numbers, _ and -")
    if len(payload.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    # Check if this Supabase account was already migrated
    already = db.table("human_users").select("id, username").eq("id", supabase_id).execute()
    if already.data:
        # Already migrated — just return a fresh token
        user = already.data[0]
        token = _issue_jwt(user["id"], user["username"])
        return {"token": token, "username": user["username"], "id": user["id"], "migrated": False}

    # Check username not taken
    name_taken = db.table("human_users").select("id").eq("username", username).execute()
    if name_taken.data:
        raise HTTPException(400, "Username already taken — choose another")

    pw_hash = _pwd.hash(payload.password)
    ip = _get_ip(request)
    try:
        # Use the Supabase UUID as the primary key so bot_profiles.owner_id still links correctly
        res = db.table("human_users").insert({
            "id": supabase_id,
            "username": username,
            "password_hash": pw_hash,
            "ip_address": ip,
            "migrated_from_email": supabase_email,
        }).execute()
    except Exception as exc:
        raise HTTPException(500, f"Migration failed: {exc}")

    user = res.data[0]
    token = _issue_jwt(user["id"], user["username"])
    return {"token": token, "username": user["username"], "id": user["id"], "migrated": True}


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


# ── endpoints ─────────────────────────────────────────────────────────────
