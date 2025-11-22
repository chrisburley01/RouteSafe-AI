# ===========================
# RouteSafe-AI Backend v5.x
# ===========================
#
# - Geocodes start/end (with UK postcode normaliser)
# - Calls ORS HGV routing
# - Runs BridgeEngine against the route geometry
# - Returns route + bridge risk summary for Navigator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import requests
import os
import re

from bridge_engine import BridgeEngine, BridgeCheckResult

# ORS API key from environment
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    raise RuntimeError("ORS_API_KEY environment variable is not set")

# ------------- FastAPI app -------------

app = FastAPI(
    title="RouteSafe-AI",
    version="5.x",
    description="HGV low-bridge routing engine – ORS + UK bridge dataset",
)

# Allow Navigator (and future front-ends) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global bridge engine instance
bridge_engine = BridgeEngine(csv_path="bridge_heights_clean.csv")


# ------------- Helpers -------------

def normalise_uk_postcode(value: str) -> str:
    """
    Turn LS270BN → LS27 0BN, HD50RJ → HD5 0RJ etc.
    Only applied to strings that *look* like UK postcodes.
    """
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    # Only normalise plausible UK postcodes
    if not (5 <= len(raw) <= 7):
        return value.strip()

    return f"{raw[:-3]} {raw[-3:]}"


def geocode_address(query: str) -> (float, float):
    """
    Geocode using ORS /geocode/search, returning (lon, lat).
    """
    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query}

    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS geocode failed ({r.status_code}) for: {query}",
        )

    data = r.json()
    if not data.get("features"):
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {query}")

    coords = data["features"][0]["geometry"]["coordinates"]
    return coords[0], coords[1]  # lon, lat


# ------------- Models -------------

class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ------------- Main route endpoint -------------

@app.post("/api/route")
def create_route(req: RouteRequest) -> Dict[str, Any]:
    # 1) Normalise postcodes
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) Geocode
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) ORS HGV routing
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ],
        # Ask ORS to give us actual coordinates for the polyline
        "geometry": True,
        "geometry_format": "geojson",
        "instructions": False,
    }
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post(url, json=body, headers=headers, timeout=40)

    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS routing failed ({r.status_code}): {r.text[:300]}",
        )

    route = r.json()

    # Defensive: make sure we have geometry coordinates
    try:
        route_geometry = route["routes"][0]["geometry"]
        coords_lonlat: List[List[float]] = route_geometry["coordinates"]
    except Exception:
        raise HTTPException(status_code=400, detail="No route returned from ORS.")

    # 4) Bridge engine: check this route for low-bridge risk
    bridge_result: BridgeCheckResult = bridge_engine.check_route(
        route_coords_lonlat=coords_lonlat,
        vehicle_height_m=req.vehicle_height_m,
    )

    # 5) Friendly metrics for Navigator
    distance_km: Optional[float] = None
    duration_min: Optional[float] = None
    try:
        s = route["routes"][0].get("summary") or {}
        distance_km = s.get("distance", 0) / 1000.0
        duration_min = s.get("duration", 0) / 60.0
    except Exception:
        pass

    bridge_summary: Dict[str, Any] = {
        "has_conflict": bridge_result.has_conflict,
        "near_height_limit": bridge_result.near_height_limit,
        "nearest_bridge": None,
        "nearest_distance_m": bridge_result.nearest_distance_m,
    }
    if bridge_result.nearest_bridge:
        bridge_summary["nearest_bridge"] = {
            "lat": bridge_result.nearest_bridge.lat,
            "lon": bridge_result.nearest_bridge.lon,
            "height_m": bridge_result.nearest_bridge.height_m,
        }

    return {
        "ok": True,
        "start_used": start_query,
        "end_used": end_query,
        "vehicle_height_m": req.vehicle_height_m,
        "avoid_low_bridges": req.avoid_low_bridges,
        "route": route,
        "route_metrics": {
            "distance_km": distance_km,
            "duration_min": duration_min,
        },
        "bridge_summary": bridge_summary,
    }


# ------------- Health check -------------

@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route",
    }