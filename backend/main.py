# backend/main.py

import os
from typing import List, Tuple, Optional, Dict, Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bridge_engine import BridgeEngine


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    # Fast fail if the key is missing – easier to diagnose
    raise RuntimeError("ORS_API_KEY environment variable is not set")

# Path to the bridge CSV – must be in the same folder as this file on Render
BRIDGE_CSV_PATH = "bridge_heights_clean.csv"

# How close a bridge has to be to the route line to be "in conflict" (metres)
SEARCH_RADIUS_M = 300.0
CONFLICT_CLEARANCE_M = 0.0   # 0m = anything lower than vehicle height
NEAR_CLEARANCE_M = 0.25      # within 25cm is also flagged


# -----------------------------------------------------------------------------
# App + CORS
# -----------------------------------------------------------------------------

app = FastAPI(title="RouteSafe AI Backend", version="0.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chrisburley01.github.io",
        "http://localhost:4173",
        "http://localhost:5173",
        "*",  # relax for now during testing
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Bridge engine
# -----------------------------------------------------------------------------

try:
    bridge_engine = BridgeEngine(
        csv_path=BRIDGE_CSV_PATH,
        search_radius_m=SEARCH_RADIUS_M,
        conflict_clearance_m=CONFLICT_CLEARANCE_M,
        near_clearance_m=NEAR_CLEARANCE_M,
    )
except Exception as e:
    # If this blows up you’ll see it clearly in Render logs
    raise RuntimeError(f"Failed to load bridge CSV '{BRIDGE_CSV_PATH}': {e}")


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

class RouteRequest(BaseModel):
    depot_postcode: str
    stop_postcodes: List[str]
    vehicle_height_m: float


class LegResponse(BaseModel):
    from_postcode: str
    to_postcode: str
    distance_km: float
    duration_min: float
    low_bridge: bool
    min_clearance_m: Optional[float] = None
    offending_bridges: List[Dict[str, Any]] = []


class RouteResponse(BaseModel):
    total_distance_km: float
    total_duration_min: float
    legs: List[LegResponse]


# -----------------------------------------------------------------------------
# Helpers – ORS
# -----------------------------------------------------------------------------

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    """
    Geocode using OpenRouteService Search API.
    Returns (lat, lon).
    """
    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": postcode,
        "boundary.country": "GB",
        "size": 1,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ORS geocode error: {e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"ORS geocode HTTP {resp.status_code}: {resp.text}",
        )

    data = resp.json()
    features = data.get("features", [])
    if not features:
        raise HTTPException(
            status_code=400,
            detail=f"Could not geocode postcode '{postcode}'",
        )

    coords = features[0]["geometry"]["coordinates"]
    lon, lat = coords[0], coords[1]
    return lat, lon


def ors_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> Tuple[float, float, List[Tuple[float, float]]]:
    """
    Call ORS Directions (driving-hgv) for a single leg.
    Returns (distance_km, duration_min, list_of_(lat, lon) along route).
    """
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    params = {
        "api_key": ORS_API_KEY,
        "start": f"{start_lon},{start_lat}",
        "end": f"{end_lon},{end_lat}",
    }

    try:
        resp = requests.get(url, params=params, timeout=20)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ORS directions error: {e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"ORS directions HTTP {resp.status_code}: {resp.text}",
        )

    data = resp.json()
    features = data.get("features", [])
    if not features:
        raise HTTPException(
            status_code=502,
            detail="ORS directions response missing features",
        )

    props = features[0]["properties"]
    summary = props.get("summary", {})
    distance_m = summary.get("distance", 0.0)
    duration_s = summary.get("duration", 0.0)

    geometry = features[0]["geometry"]
    coords = geometry.get("coordinates", [])
    # ORS coords are [lon, lat]; convert to (lat, lon)
    route_points = [(c[1], c[0]) for c in coords]

    distance_km = distance_m / 1000.0
    duration_min = duration_s / 60.0

    return distance_km, duration_min, route_points


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "ok", "service": "RouteSafe AI backend"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/route", response_model=RouteResponse)
def calculate_route(req: RouteRequest):
    """
    Main endpoint used by the front end.
    - Geocodes depot + stops with ORS
    - Gets ORS HGV route for each leg
    - Checks each leg against UK bridge CSV
    """
    if not req.stop_postcodes:
        raise HTTPException(status_code=400, detail="At least one stop is required")

    # Cache geocodes so we don't call ORS twice for the same postcode
    geo_cache: Dict[str, Tuple[float, float]] = {}

    def get_latlon(pc: str) -> Tuple[float, float]:
        if pc not in geo_cache:
            geo_cache[pc] = geocode_postcode(pc)
        return geo_cache[pc]

    all_points = [req.depot_postcode] + req.stop_postcodes

    legs: List[LegResponse] = []
    total_distance_km = 0.0
    total_duration_min = 0.0

    for i in range(len(all_points) - 1):
        from_pc = all_points[i]
        to_pc = all_points[i + 1]

        from_lat, from_lon = get_latlon(from_pc)
        to_lat, to_lon = get_latlon(to_pc)

        distance_km, duration_min, route_points = ors_route(
            from_lat, from_lon, to_lat, to_lon
        )

        # Bridge analysis
        analysis = bridge_engine.analyze_route(
            route_points, vehicle_height_m=req.vehicle_height_m
        )

        leg = LegResponse(
            from_postcode=from_pc,
            to_postcode=to_pc,
            distance_km=round(distance_km, 2),
            duration_min=round(duration_min, 1),
            low_bridge=analysis.get("conflicting", False),
            min_clearance_m=analysis.get("min_clearance_m"),
            offending_bridges=analysis.get("bridges", []),
        )

        legs.append(leg)
        total_distance_km += distance_km
        total_duration_min += duration_min

    return RouteResponse(
        total_distance_km=round(total_distance_km, 2),
        total_duration_min=round(total_duration_min, 1),
        legs=legs,
    )
