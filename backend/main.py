# ===========================
# RouteSafe-AI Backend v5.0R
# (no polyline, robust errors + static UI)
# ===========================

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import re
import requests
from pathlib import Path

from bridge_engine import BridgeEngine  # uses bridge_heights_clean.csv

# ---------------------------
# Paths
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # repo root
WEB_DIR = BASE_DIR / "web"

# ORS API key from Render env
ORS_API_KEY = os.getenv("ORS_API_KEY")
if not ORS_API_KEY:
    ORS_API_KEY = None

app = FastAPI(
    title="RouteSafe-AI",
    version="5.0R-no-polyline",
    description="HGV low-bridge routing engine – avoid low bridges",
)

# Serve /static/* from the web folder (styles.css, app.js, etc.)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# ------------------------------------------------------------
# Bridge engine startup
# ------------------------------------------------------------
try:
    bridge_engine = BridgeEngine(
        csv_path=str(BASE_DIR / "backend" / "bridge_heights_clean.csv"),
        search_radius_m=300.0,
        conflict_clearance_m=0.0,
        near_clearance_m=0.25,
    )
    BRIDGE_ENGINE_OK = True
    BRIDGE_ENGINE_ERROR = None
except Exception as e:
    bridge_engine = None
    BRIDGE_ENGINE_OK = False
    BRIDGE_ENGINE_ERROR = str(e)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def normalise_uk_postcode(value: str) -> str:
    """
    Turn LS270BN -> LS27 0BN, hd50rl -> HD5 0RL, etc.
    If it doesn't look like a UK postcode length, return as-is.
    """
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    if not (5 <= len(raw) <= 7):
        return value.strip()

    return f"{raw[:-3]} {raw[-3:]}"


def geocode_address(query: str):
    """
    Geocode using ORS /geocode/search.
    Returns (lon, lat).
    """
    if not ORS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ORS_API_KEY not configured on server.",
        )

    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query}

    r = requests.get(url, params=params, timeout=20)

    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS geocode failed for '{query}': {r.text}",
        )

    data = r.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to geocode: {query}",
        )

    coords = features[0]["geometry"]["coordinates"]
    # ORS returns [lon, lat]
    return coords[0], coords[1]


def get_ors_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float):
    """
    Minimal ORS HGV route call: just coordinates, no geometry_format, etc.
    """
    if not ORS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ORS_API_KEY not configured on server.",
        )

    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ]
    }
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post(url, json=body, headers=headers, timeout=40)

    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS routing failed: {r.text}",
        )

    data = r.json()
    routes = data.get("routes") or []
    if not routes:
        raise HTTPException(
            status_code=400,
            detail="No route returned from ORS.",
        )

    return routes[0]


# ------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------

class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


class BridgeRiskSummary(BaseModel):
    has_conflict: bool
    near_height_limit: bool
    nearest_bridge_height_m: float | None
    nearest_bridge_distance_m: float | None
    note: str | None = None


class RouteResponse(BaseModel):
    ok: bool
    start_used: str
    end_used: str
    distance_m: float
    duration_s: float
    bridge_risk: BridgeRiskSummary
    raw_route: dict


# ------------------------------------------------------------
# Main routing endpoint
# ------------------------------------------------------------

@app.post("/api/route", response_model=RouteResponse)
def create_route(req: RouteRequest):
    # 1) Normalise postcodes
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) Geocode both
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) Ask ORS for an HGV route
    ors_route = get_ors_route(start_lon, start_lat, end_lon, end_lat)
    summary = ors_route.get("summary", {})
    distance_m = float(summary.get("distance", 0.0))
    duration_s = float(summary.get("duration", 0.0))

    # 4) Bridge risk assessment (straight-line leg for now)
    if not BRIDGE_ENGINE_OK or bridge_engine is None:
        bridge_risk = BridgeRiskSummary(
            has_conflict=False,
            near_height_limit=False,
            nearest_bridge_height_m=None,
            nearest_bridge_distance_m=None,
            note=f"Bridge engine unavailable: {BRIDGE_ENGINE_ERROR}",
        )
    elif not req.avoid_low_bridges:
        bridge_risk = BridgeRiskSummary(
            has_conflict=False,
            near_height_limit=False,
            nearest_bridge_height_m=None,
            nearest_bridge_distance_m=None,
            note="Bridge check skipped (avoid_low_bridges = false).",
        )
    else:
        try:
            result = bridge_engine.check_leg(
                (start_lat, start_lon),
                (end_lat, end_lon),
                vehicle_height_m=req.vehicle_height_m,
            )

            nearest_h = (
                result.nearest_bridge.height_m
                if result.nearest_bridge is not None
                else None
            )

            bridge_risk = BridgeRiskSummary(
                has_conflict=result.has_conflict,
                near_height_limit=result.near_height_limit,
                nearest_bridge_height_m=nearest_h,
                nearest_bridge_distance_m=result.nearest_distance_m,
                note=None,
            )
        except Exception as e:
            bridge_risk = BridgeRiskSummary(
                has_conflict=False,
                near_height_limit=False,
                nearest_bridge_height_m=None,
                nearest_bridge_distance_m=None,
                note=f"Bridge check error: {e}",
            )

    return RouteResponse(
        ok=True,
        start_used=start_query,
        end_used=end_query,
        distance_m=distance_m,
        duration_s=duration_s,
        bridge_risk=bridge_risk,
        raw_route=ors_route,
    )


# ------------------------------------------------------------
# UI + status endpoints
# ------------------------------------------------------------

@app.get("/")
async def serve_index():
    """Serve the nice frontend UI at the root URL."""
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


@app.get("/api/status")
def status():
    """JSON health/status endpoint."""
    return {
        "service": "RouteSafe-AI",
        "version": "5.0R-no-polyline",
        "status": "ok",
        "bridge_engine_ok": BRIDGE_ENGINE_OK,
        "bridge_engine_error": BRIDGE_ENGINE_ERROR,
        "message": "HGV low-bridge routing engine – use POST /api/route",
    }