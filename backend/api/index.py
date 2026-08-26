"""Vercel entrypoint. Vercel's Python runtime auto-detects this module's `app` as an ASGI
application; backend/vercel.json's catch-all rewrite sends every path here, so the route
structure defined in app/main.py needs no /api prefix and no changes for this deployment target.

Docker and Render don't use this file at all — they run `uvicorn app.main:app` directly
(see backend/Dockerfile).
"""

from app.main import app

__all__ = ["app"]
