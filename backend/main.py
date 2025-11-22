# ===========================
# RouteSafe-AI Backend v5.0R
# ===========================
#
# - FastAPI service for low-bridge-aware HGV routing
# - Uses OpenRouteService for routing + geocoding
# - Uses BridgeEngine (bridge_engine.py + bridge_heights_clean.csv)
#   to check for low-bridge conflicts on the leg.
#
# IMPORTANT:
#   * No polyline library
#   * No geometry_format parameter (keeps ORS happy)
#
#   Root: GET  /           -> service status
#   Route: POST /api/route -> calculate route + bridge risk

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

import os
import re
import requests

from bridge_engine import BridgeEngine, BridgeCheckResult


# ---------------------------------
# Config – ORS API key from ENV
# ---------------------------------
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    # Don't crash the process on import, but fail all route calls
    # with a clear error if the key is missing.
    print("[RouteSafe-AI] WARNING: ORS_API_KEY is not set in environment")


# ---------------------------------
# FastAPI app
# ---------------------------------
app = FastAPI(
    title="RouteSafe-AI",
    version="5.0R-no-polyline",
    description="HGV low-bridge routing engine – avoid low bridges"
)


# ---------------------------------
# UK POSTCODE NORMALISER
# ---------------------------------
def normalise_uk_postcode(value: str) -> str:
    """
    Clean up badly formatted postcodes like:
      LS270BN  -> LS27 0BN
      hd50rl   -> HD5 0RL
      ' LS27-0bn ' -> LS27 0BN
    """
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    # Only normalise things that look like postcodes
    if not (5 <= len(raw) <= 7):
        return value.strip()

    return f"{raw[:-3]} {raw[-3:]}"


# ---------------------------------
# Request model
# ---------------------------------
class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ---------------------------------
# Bridge engine instance
# ---------------------------------
bridge_engine = BridgeEngine(
    csv_path="bridge_heights_clean.csv",
    search_radius_m=300.0,
    conflict_clearance_m=0.0,
    near_clearance_m=0.25,
)


# ---------------------------------
# Helper: ORS geocoding
# ---------------------------------
def geocode_address(query: str):
    if not ORS_API_KEY:
        raise HTTPException(status_code=500, detail="ORS_API_KEY not configured")

    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": query,
        "size": 1,
    }

    r = requests.get(url, params=params, timeout=15)
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS geocode failed for '{query}': {r.text}",
        )

    data = r.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {query}")

    coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
    lon, lat = coords[0], coords[1]
    return lon, lat


# ---------------------------------
# Helper: ORS routing (driving-hgv)
# ---------------------------------
def ors_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float) -> Dict[str, Any]:
    if not ORS_API_KEY:
        raise HTTPException(status_code=500, detail="ORS_API_KEY not configured")

    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ],
        # Keep it simple – we don't depend on turn-by-turn right now
        "instructions": False,
        "geometry_simplify": False,
    }

    # NOTE: NO geometry_format param here – avoids the 2012 error.
    r = requests.post(url, json=body, headers=headers, timeout=30)

    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS routing failed (status {r.status_code}): {r.text}",
        )

    data = r.json()
    routes = data.get("routes") or []
    if not routes:
        raise HTTPException(status_code=400, detail="No route returned from ORS.")

    return routes[0]  # first / primary route


# ---------------------------------
# POST /api/route
# ---------------------------------
@app.post("/api/route")
def create_route(req: RouteRequest) -> Dict[str, Any]:
    """
    Main entry: given start/end + vehicle height, return:
      - ORS HGV route
      - bridge risk assessment for the leg
    """

    # 1) Clean postcodes
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) Geocode
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) Get HGV route from ORS
    route = ors_route(start_lon, start_lat, end_lon, end_lat)

    summary = route.get("summary", {}) or {}
    distance_m = summary.get("distance")
    duration_s = summary.get("duration")

    # 4) Bridge risk check (straight-line leg using our engine)
    bridge_result: Optional[BridgeCheckResult] = None
    if req.avoid_low_bridges:
        bridge_result = bridge_engine.check_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=req.vehicle_height_m,
        )

    # Prepare bridge risk payload
    bridge_payload: Optional[Dict[str, Any]] = None
    if bridge_result:
        nearest_bridge = None
        if bridge_result.nearest_bridge is not None:
            nearest_bridge = {
                "lat": bridge_result.nearest_bridge.lat,
                "lon": bridge_result.nearest_bridge.lon,
                "height_m": bridge_result.nearest_bridge.height_m,
            }

        bridge_payload = {
            "has_conflict": bridge_result.has_conflict,
            "near_height_limit": bridge_result.near_height_limit,
            "nearest_bridge": nearest_bridge,
            "nearest_distance_m": bridge_result.nearest_distance_m,
        }

    # 5) Response
    return {
        "ok": True,
        "engine_version": "5.0R-no-polyline",
        "start_used": start_query,
        "end_used": end_query,
        "summary": {
            "distance_m": distance_m,
            "duration_s": duration_s,
        },
        "bridge_risk": bridge_payload,
        # We pass the raw ORS route object back – Navigator (later) can use it.
        "route": route,
    }


# ---------------------------------
# GET /
# ---------------------------------
@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "RouteSafe-AI",
        "version": "5.0R-no-polyline",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route",
    }