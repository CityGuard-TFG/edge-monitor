"""CityGuard Edge Monitor -- read-only status dashboard backend.

Not part of the anonymization/capture/upload pipeline. No auth. LAN-only.
See ../../README.md for the operational caveats (unauthenticated, raw camera
preview) before running this on a device operating around the public.
"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import camera, gps_client, hailo, status

logger = logging.getLogger("cityguard.edge_monitor")

app = FastAPI(title="CityGuard Edge Monitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _on_startup():
    gps_client.start_background_thread()


@app.get("/api/health")
def health():
    return {"ok": True}


app.include_router(status.router, prefix="/api")
app.include_router(hailo.router, prefix="/api")
app.include_router(gps_client.router, prefix="/api")
app.include_router(camera.router, prefix="/api")

# Serve the built frontend (web/dist), mounted after /api so /api/* keeps
# priority. server/app/main.py -> ../../web/dist.
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")
else:
    logger.warning(
        "Frontend build not found at %s -- run `npm run build` in web/ to serve the dashboard UI.",
        _frontend_dist,
    )
