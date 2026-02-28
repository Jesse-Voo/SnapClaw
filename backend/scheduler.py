"""
Global APScheduler instance shared across the app.
Import `get_scheduler()` as a FastAPI dependency or call `scheduler` directly.
"""
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()


def get_scheduler() -> BackgroundScheduler:
    return scheduler
