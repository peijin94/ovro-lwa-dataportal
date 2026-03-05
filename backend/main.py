"""FastAPI app for LWA Data Portal; serve under /portal/*."""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.routes.portal import router as portal_router
from backend.visitors import record_visit

app = FastAPI(title="LWA Data Portal API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    # Record this visit (best-effort; failures are logged but non-fatal)
    record_visit(request)

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
