# backend/main.py

import math
import os
from typing import List, Tuple, Any, Dict

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bridge_engine import BridgeEngine

# ---------- CONFIG ---------- #

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "RouteSafeAI/0.3 (contact: you@example.com)"

# You can still keep ORS_API_KEY in env for later if we upgrade routing
ORS_API_KEY = os.environ.get("ORS_API_KEY")

app = FastAPI(title="RouteSafe AI Backend", version="0.3")

# Allow your GitHub Pages front end
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chrisburley01.github.io",
        "http://chrisburley01.github.io",
        "https://chrisburley01.github.io/",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- BRIDGE ENGINE ---------- #

try:
    bridge_engine = BridgeEngine(
        csv_path="bridge_heights_clean.csv",
        search_radius_m=1000.0,
        conflict_clearance_m=0.0,
        near_clearance_m=0.25,
    )
except Exception as e:
    raise RuntimeError(f"Could not load bridge CSV: {e}") from e


def low_bridges_for_leg(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    vehicle_height_m: float,
) -> List[Dict[str, Any]]:
    """
    Adapter around BridgeEngine – handles whichever method name we ended up with.
    Returns a list of dicts for bridges which conflict with vehicle_height_m.
    """
    if hasattr(bridge_engine, "check_leg_for_low_bridges"):
        return bridge_engine.check_leg_for_low_bridges(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=vehicle_height_m,
        )
    if hasattr(bridge_engine, "find_low_bridges_along_leg"):
        return bridge_engine.find_low_bridges_along_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=vehicle_height_m,
        )
    if hasattr(bridge_engine, "get_low_bridges_for_leg"):
        return bridge_engine.get_low_bridges_for_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=vehicle_height_m,
        )

    # Fallback – no bridge check implemented
    return []


# ---------- MODELS ---------- #

class RouteRequest(BaseModel):
    depot_postcode: str
    stops: List[str]
    vehicle_height_m: float


class BridgeHit(BaseModel):
    id: str | None = None
    name: str | None = None
    height_m: float
    lat: float
    lon: float
    clearance_m: float


class Leg(BaseModel):
    from_postcode: str
    to_postcode: str
    distance_km: float
    duration_min: float
    google_maps_url: str
    low_bridges: List[BridgeHit]


class RouteResponse(BaseModel):
    total_distance_km: float
    total_duration_min: float
    legs: List[Leg]


# ---------- HELPERS ---------- #

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    """Look up lat/lon for a UK postcode using Nominatim."""
    params = {"q": postcode, "format": "json", "limit": 1}
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nominatim error: {e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Nominatim HTTP {resp.status_code}: {resp.text}",
        )

    data = resp.json()
    if not data:
        raise HTTPException(status_code=400, detail=f"Could not geocode '{postcode}'")

    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return lat, lon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ---------- ROUTES ---------- #

@app.get("/")
def root():
    return {"status": "ok", "message": "RouteSafe AI backend running"}


@app.post("/plan_route", response_model=RouteResponse)
def plan_route(request: RouteRequest):
    """
    Main endpoint used by the frontend.
    Takes depot + stops + vehicle height, returns legs & low bridge warnings.
    """
    if not request.stops:
        raise HTTPException(status_code=400, detail="At least one stop is required")

    # Build seq of all postcodes
    postcodes: List[str] = [request.depot_postcode] + request.stops

    # Geocode each point
    coords: List[Tuple[float, float]] = []
    for pc in postcodes:
        coords.append(geocode_postcode(pc))

    total_dist_km = 0.0
    total_dur_min = 0.0
    legs: List[Leg] = []

    # Simple road distance/time approximation:
    # - straight-line distance * 1.2 (wiggle factor)
    # - average speed 40 km/h
    ROAD_WIGGLE_FACTOR = 1.2
    AVG_SPEED_KMH = 40.0

    for i in range(len(postcodes) - 1):
        from_pc = postcodes[i]
        to_pc = postcodes[i + 1]
        (lat1, lon1) = coords[i]
        (lat2, lon2) = coords[i + 1]

        straight_km = haversine_km(lat1, lon1, lat2, lon2)
        distance_km = straight_km * ROAD_WIGGLE_FACTOR
        duration_min = (distance_km / AVG_SPEED_KMH) * 60.0

        # Bridge checks
        bridges_raw = low_bridges_for_leg(
            start_lat=lat1,
            start_lon=lon1,
            end_lat=lat2,
            end_lon=lon2,
            vehicle_height_m=request.vehicle_height_m,
        )

        bridge_hits: List[BridgeHit] = []
        for b in bridges_raw:
            try:
                height_m = float(b.get("height_m"))
            except Exception:
                # If height missing or bad, skip the bridge
                continue

            bridge_hits.append(
                BridgeHit(
                    id=str(
                        b.get("bridge_id")
                        or b.get("BRIDGE_ID")
                        or b.get("id")
                        or ""
                    )
                    or None,
                    name=(
                        b.get("name")
                        or b.get("description")
                        or b.get("location")
                        or None
                    ),
                    height_m=height_m,
                    lat=float(b.get("lat")),
                    lon=float(b.get("lon")),
                    clearance_m=float(b.get("clearance_m", 0.0)),
                )
            )

        gmaps_url = (
            "https://www.google.com/maps/dir/"
            f"{from_pc.replace(' ', '+')}/{to_pc.replace(' ', '+')}"
        )

        leg = Leg(
            from_postcode=from_pc,
            to_postcode=to_pc,
            distance_km=round(distance_km, 1),
            duration_min=round(duration_min),
            google_maps_url=gmaps_url,
            low_bridges=bridge_hits,
        )

        legs.append(leg)
        total_dist_km += distance_km
        total_dur_min += duration_min

    return RouteResponse(
        total_distance_km=round(total_dist_km, 1),
        total_duration_min=round(total_dur_min),
        legs=legs,
    )
