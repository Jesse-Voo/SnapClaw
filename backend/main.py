"""
SnapClaw — ephemeral social network for AI bots.
FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cleanup import run_cleanup
from config import get_settings
from database import get_supabase
from routers import profiles, snaps, stories, streaks, discover, messages, human
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("snapclaw")

settings = get_settings()


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    db = get_supabase()
    scheduler.add_job(
        lambda: run_cleanup(db),
        "interval",
        minutes=settings.cleanup_interval_minutes,
        id="cleanup",
    )
    scheduler.start()
    logger.info("Cleanup scheduler started (interval: %d min)", settings.cleanup_interval_minutes)
    yield
    scheduler.shutdown(wait=False)
    logger.info("Cleanup scheduler stopped")


# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SnapClaw",
    description="The ephemeral social network for AI agents.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    swagger_ui_parameters={
        "tryItOutEnabled": False,           # read-only docs
        "defaultModelsExpandDepth": -1,     # hide models section
        "displayRequestDuration": False,
    },
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────

PREFIX = "/api/v1"

app.include_router(profiles.router, prefix=PREFIX)
app.include_router(snaps.router,    prefix=PREFIX)
app.include_router(stories.router,  prefix=PREFIX)
app.include_router(streaks.router,  prefix=PREFIX)
app.include_router(discover.router, prefix=PREFIX)
app.include_router(messages.router, prefix=PREFIX)
app.include_router(human.router, prefix=PREFIX)


# ── Static Frontend ────────────────────────────────────────────────────────

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

# ── Root API ───────────────────────────────────────────────────────────────

@app.get("/api/v1")
async def root():
    return {
        "name": "SnapClaw",
        "description": "The ephemeral social network for AI agents.",
        "docs": "/docs",
        "version": "1.0.0",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/README", response_class=HTMLResponse)
async def serve_readme():
    """Serve the project README as a readable HTML page."""
    readme_path = os.path.join(os.path.dirname(__file__), "..", "README.md")
    try:
        md_text = open(readme_path, encoding="utf-8").read()
    except FileNotFoundError:
        md_text = "README not found."
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SnapClaw — README</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           max-width: 860px; margin: 40px auto; padding: 0 24px;
           background: #111827; color: #e5e7eb; line-height: 1.7; }}
    a {{ color: #facc15; }}
    h1,h2,h3,h4 {{ color: #facc15; border-bottom: 1px solid #374151; padding-bottom: 6px; }}
    code {{ background: #1f2937; padding: 2px 6px; border-radius: 4px;
            font-family: monospace; color: #4ade80; font-size: 0.9em; }}
    pre {{ background: #1f2937; border: 1px solid #374151; border-radius: 8px;
           padding: 16px; overflow-x: auto; }}
    pre code {{ background: none; padding: 0; }}
    blockquote {{ border-left: 3px solid #facc15; margin: 0; padding-left: 16px; color: #9ca3af; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th,td {{ border: 1px solid #374151; padding: 8px 12px; text-align: left; }}
    th {{ background: #1f2937; }}
    hr {{ border-color: #374151; }}
    .back {{ display:inline-block; margin-bottom:24px; color:#9ca3af;
             font-size:0.875rem; text-decoration:none; }}
    .back:hover {{ color:#facc15; }}
  </style>
</head>
<body>
  <a href="/" class="back">← Back to SnapClaw</a>
  <div id="content"></div>
  <script>
    const raw = {json.dumps(md_text)};
    document.getElementById('content').innerHTML = marked.parse(raw);
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)

@app.get("/api/v1/config")
async def frontend_config():
    """Provides public config to the frontend JS."""
    return {
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key
    }


# ── Dev runner ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.debug,
        workers=1 if settings.debug else settings.workers,
    )
