# main.py
#
# RouteSafe AI – Bridge Clearance Checker
# ---------------------------------------
# For each leg (Depot -> Stop1, Stop1 -> Stop2, ...):
#   - Geocodes postcodes (GB)
#   - Estimates distance/time
#   - Uses BridgeEngine + Network Rail heights (in metres)
#   - Flags:
#       safe            = no low bridge issue
#       near_height     = within margin above vehicle
#       unsafe          = at least one bridge lower than vehicle
#
# No re-routing – just clearance checks.

import math
from typing import List, Dict, Tuple, Optional

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bridge_engine import BridgeEngine


USER_AGENT = "RouteSafeAI/0.2 (contact: routesafe@example.com)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"

app = FastAPI(title="RouteSafe AI", version="0.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chrisburley01.github.io",
        "https://chrisburley01.github.io/RouteSafe-AI",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Bridge engine using cleaned Network Rail CSV (lat, lon, height_m) --- #

bridge_engine = BridgeEngine(
    csv_path="bridge_heights_clean.csv",
    search_radius_m=300.0,    # how close to leg to count as "on route"
    conflict_clearance_m=0.0, # < vehicle_height_m = unsafe
    near_clearance_m=0.25,    # within 0.25m above vehicle = near height limit
)


# -------------------- Models -------------------- #

class RouteRequest(BaseModel):
    depot_postcode: str
    delivery_postcodes: List[str]
    vehicle_height_m: float


class BridgeInfo(BaseModel):
    lat: float
    lon: float
    height_m: float
    distance_m: float
    clearance_m: float


class Leg(BaseModel):
    from_: str
    to: str
    distance_km: float
    duration_min: float
    safe: bool
    near_height_limit: bool
    has_conflict: bool
    bridge: Optional[BridgeInfo] = None


class RouteResponse(BaseModel):
    total_distance_km: float
    total_duration_min: float
    legs: List[Leg]


# -------------------- Geocoding + distance -------------------- #

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    params = {
        "q": postcode,
        "format": "json",
        "limit": 1,
        "countrycodes": "gb",
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(
            f"{NOMINATIM_URL}/search",
            params=params,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Geocoding error: {e}")

    data = resp.json()
    if not data:
        raise HTTPException(status_code=404, detail=f"Could not geocode postcode: {postcode}")

    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return lat, lon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def estimate_leg(
    from_pc: str,
    to_pc: str,
    cache: Dict[str, Tuple[float, float]],
) -> Tuple[float, float, float, float]:
    """
    Straight-line distance * 1.3 as rough road estimate.
    Returns: distance_km, duration_min, start_lat, start_lon, end_lat, end_lon
    """
    if from_pc not in cache:
        cache[from_pc] = geocode_postcode(from_pc)
    if to_pc not in cache:
        cache[to_pc] = geocode_postcode(to_pc)

    lat1, lon1 = cache[from_pc]
    lat2, lon2 = cache[to_pc]

    crow_km = haversine_km(lat1, lon1, lat2, lon2)
    road_km = crow_km * 1.3  # crude fudge factor
    duration_hours = road_km / 60.0  # assume avg 60km/h
    duration_min = duration_hours * 60.0

    return road_km, duration_min, lat1, lon1, lat2, lon2


# -------------------- API endpoints -------------------- #

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "RouteSafe AI",
        "mode": "bridge_clearance_checker",
        "version": "0.3",
    }


@app.post("/route", response_model=RouteResponse)
def route_endpoint(request: RouteRequest):
    depot = request.depot_postcode.strip().upper()
    deliveries = [pc.strip().upper() for pc in request.delivery_postcodes if pc.strip()]

    if not depot:
        raise HTTPException(status_code=400, detail="Depot postcode is required.")
    if not deliveries:
        raise HTTPException(status_code=400, detail="At least one delivery postcode is required.")
    if request.vehicle_height_m <= 0:
        raise HTTPException(status_code=400, detail="Vehicle height must be > 0.")

    all_points = [depot] + deliveries
    legs: List[Leg] = []
    total_distance = 0.0
    total_duration = 0.0

    # cache geocodes so we don't hit Nominatim multiple times for same postcode
    geo_cache: Dict[str, Tuple[float, float]] = {}

    for i in range(len(all_points) - 1):
        from_pc = all_points[i]
        to_pc = all_points[i + 1]

        distance_km, duration_min, lat1, lon1, lat2, lon2 = estimate_leg(
            from_pc, to_pc, geo_cache
        )

        # Run bridge clearance check on this leg
        br = bridge_engine.check_leg(
            start_lat=lat1,
            start_lon=lon1,
            end_lat=lat2,
            end_lon=lon2,
            vehicle_height_m=request.vehicle_height_m,
        )

        safe = not br.has_conflict
        near_limit = br.near_height_limit
        has_conflict = br.has_conflict

        bridge_info: Optional[BridgeInfo] = None
        if br.nearest_bridge is not None and br.nearest_distance_m is not None:
            clearance_m = br.nearest_bridge.height_m - request.vehicle_height_m
            bridge_info = BridgeInfo(
                lat=br.nearest_bridge.lat,
                lon=br.nearest_bridge.lon,
                height_m=br.nearest_bridge.height_m,
                distance_m=br.nearest_distance_m,
                clearance_m=clearance_m,
            )

        leg = Leg(
            from_=from_pc,
            to=to_pc,
            distance_km=distance_km,
            duration_min=duration_min,
            safe=safe,
            near_height_limit=near_limit,
            has_conflict=has_conflict,
            bridge=bridge_info,
        )

        legs.append(leg)
        total_distance += distance_km
        total_duration += duration_min

    return RouteResponse(
        total_distance_km=total_distance,
        total_duration_min=total_duration,
        legs=legs,
    )


# Stub so the /ocr call doesn't crash yet – can be wired later
@app.post("/ocr")
async def ocr_stub(file: UploadFile = File(...)):
    return {"raw_text": "", "postcodes": []}