"""FastAPI app for LWA Data Portal; serve under /portal/*."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from backend.config import PORTAL_BASE_URL
from backend.routes.portal import router as portal_router
from backend.visitors import record_visit

app = FastAPI(title="LWA Data Portal API", version="0.1.0")


def _allowed_origins() -> list:
    """CORS origins for the public API.

    The portal has no cookie/session state and its SPA is served same-origin,
    so cross-origin access is only granted to explicitly listed origins:
    PORTAL_ALLOWED_ORIGINS (comma-separated) or, by default, the origin of
    PORTAL_BASE_URL and its www variant.
    """
    raw = os.environ.get("PORTAL_ALLOWED_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    parts = urlsplit(PORTAL_BASE_URL)
    origin = f"{parts.scheme}://{parts.netloc}"
    origins = [origin]
    if not parts.netloc.startswith("www."):
        origins.append(f"{parts.scheme}://www.{parts.netloc}")
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)

# API first so /portal/* takes precedence
app.include_router(portal_router)

# Path to built frontend (Vite dist)
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# Serve static assets from /assets if build exists
if frontend_dist.is_dir():
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/")
async def index(request: Request):
    """
    Main SPA entry point.

    If the Vite build exists, return dist/index.html.
    Otherwise, return a simple JSON error so the service is still observable.
    """
    # Record this visit off the event loop (best-effort; failures are
    # logged but non-fatal). Blocking SQLite must not run on the loop.
    await run_in_threadpool(record_visit, request)

    index_path = frontend_dist / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path), media_type="text/html")
    return JSONResponse(
        {"error": "frontend build not found"},
        status_code=500,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5001)
