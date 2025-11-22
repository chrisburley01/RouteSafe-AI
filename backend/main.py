# ===========================
# RouteSafe-AI Backend v5.3
# ===========================
#
# - Geocodes start/end (UK postcodes or addresses) via ORS
# - Tries HGV routing first (driving-hgv)
# - If ORS rejects (e.g. height too big), falls back to driving-car
# - Runs bridge_engine over the route geometry
# - Returns distance, duration + bridge risk summary
#
# Expected env var:
#   ORS_API_KEY  (your OpenRouteService API key)
#

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os
import re
from typing import Tuple, List, Dict, Any

from bridge_engine import BridgeEngine

# ------------------------------------------------------------
# ORS API key
# ------------------------------------------------------------
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    # Fail fast if the key is missing – easier to debug on Render
    raise RuntimeError("Environment variable ORS_API_KEY is not set")

# Single bridge engine instance (loads CSV once)
bridge_engine = BridgeEngine(
    csv_path="bridge_heights_clean.csv",
    search_radius_m=300.0,       # how far from the route to look for bridges
    conflict_clearance_m=0.0,    # < vehicle height = conflict
    near_clearance_m=0.25        # within +25cm = 'near height limit'
)

app = FastAPI(
    title="RouteSafe-AI",
    version="5.3",
    description="HGV low-bridge routing engine – avoid low bridges"
)

# ------------------------------------------------------------
# UK POSTCODE NORMALISER (LS270BN → LS27 0BN etc.)
# ------------------------------------------------------------
POSTCODE_RE = re.compile(r"[^A-Za-z0-9]")


def normalise_uk_postcode(value: str) -> str:
    """
    Clean up user-entered UK postcodes:

      "ls270bn"  -> "LS27 0BN"
      "M314QN"   -> "M31 4QN"
      "hd5 0rL"  -> "HD5 0RL"

    If it doesn't look like a UK postcode, just strip/uppercase.
    """
    if not value:
        return value

    raw = POSTCODE_RE.sub("", value).upper()

    # Only normalise values that look like UK postcodes
    if not (5 <= len(raw) <= 7):
        return value.strip().upper()

    return f"{raw[:-3]} {raw[-3:]}"


# ------------------------------------------------------------
# Request model
# ------------------------------------------------------------
class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ------------------------------------------------------------
# Geocoding using ORS
# ------------------------------------------------------------
def geocode_address(query: str) -> Tuple[float, float]:
    """
    Return (lon, lat) for a query string using ORS geocode.
    """
    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query}

    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS geocode failed ({r.status_code}): {r.text}"
        )

    data = r.json()
    if not data.get("features"):
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {query}")

    coords = data["features"][0]["geometry"]["coordinates"]
    # ORS returns [lon, lat]
    return float(coords[0]), float(coords[1])


# ------------------------------------------------------------
# ORS routing helpers
# ------------------------------------------------------------
def ors_route(profile: str,
              start_lon: float,
              start_lat: float,
              end_lon: float,
              end_lat: float) -> Dict[str, Any]:
    """
    Call ORS directions with the requested profile.

    Raises RuntimeError on any failure so the caller can
    decide whether to fall back or bubble up.
    """
    url = f"https://api.openrouteservice.org/v2/directions/{profile}"

    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat]
        ],
        # Ask ORS for geometry in GeoJSON format so we get
        # a list of [lon, lat] coordinates – easier for bridge checks.
        "instructions": True,
        "geometry": True,
        "geometry_format": "geojson"
    }
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }

    r = requests.post(url, json=body, headers=headers, timeout=40)

    if r.status_code != 200:
        raise RuntimeError(
            f"ORS {profile} routing failed ({r.status_code}): {r.text}"
        )

    data = r.json()
    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError(f"ORS {profile} returned no routes")

    return data


# ------------------------------------------------------------
# Main route endpoint
# ------------------------------------------------------------
@app.post("/api/route")
def create_route(req: RouteRequest):
    # 1) Clean the postcodes/addresses
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) Geocode via ORS
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) Try HGV routing, fall back to car if ORS rejects
    mode_used = "driving-hgv"
    try:
        route = ors_route("driving-hgv", start_lon, start_lat, end_lon, end_lat)
    except Exception:
        # HGV profile can reject >4.8m etc – fall back so we *always*
        # have something to show and can still run bridge checks.
        mode_used = "driving-car-fallback"
        try:
            route = ors_route("driving-car", start_lon, start_lat, end_lon, end_lat)
        except Exception as e2:
            raise HTTPException(
                status_code=400,
                detail=f"ORS routing failed: {str(e2)}"
            )

    first_route = route["routes"][0]
    summary = first_route.get("summary", {})
    distance_m = float(summary.get("distance", 0.0))
    duration_s = float(summary.get("duration", 0.0))

    # 4) Bridge check along the route geometry
    geometry = first_route.get("geometry", {})
    coords: List[List[float]] = geometry.get("coordinates", [])

    bridge_summary = None
    if coords and req.vehicle_height_m > 0:
        # coords are [[lon, lat], ...]
        bridge_result = bridge_engine.check_route(
            coords,
            vehicle_height_m=req.vehicle_height_m
        )

        # If user turns off avoidance we still show info,
        # but Navigator can choose how to present it.
        bridge_summary = {
            "has_conflict": bridge_result.has_conflict if req.avoid_low_bridges else False,
            "near_height_limit": bridge_result.near_height_limit,
            "nearest_bridge": (
                {
                    "lat": bridge_result.nearest_bridge.lat,
                    "lon": bridge_result.nearest_bridge.lon,
                    "height_m": bridge_result.nearest_bridge.height_m,
                }
                if bridge_result.nearest_bridge is not None
                else None
            ),
            "nearest_distance_m": bridge_result.nearest_distance_m
        }
    else:
        bridge_summary = {
            "has_conflict": False,
            "near_height_limit": False,
            "nearest_bridge": None,
            "nearest_distance_m": None,
        }

    # 5) Return combined payload for Navigator
    return {
        "ok": True,
        "start_used": start_query,
        "end_used": end_query,
        "mode": mode_used,
        "distance_m": distance_m,
        "duration_s": duration_s,
        "route": route,
        "bridge_summary": bridge_summary,
    }


# ------------------------------------------------------------
# Base endpoint
# ------------------------------------------------------------
@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route"
    }