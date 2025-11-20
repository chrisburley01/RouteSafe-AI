import os
from typing import List, Dict, Tuple, Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bridge_engine import BridgeEngine


# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    # Still warn in logs, but let the app start
    print("WARNING: ORS_API_KEY environment variable is not set.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_CSV_PATH = os.path.join(BASE_DIR, "bridge_heights_clean.csv")

# Initialise bridge engine once at startup
bridge_engine = BridgeEngine(BRIDGE_CSV_PATH)


# -------------------------------------------------------------------
# FastAPI setup
# -------------------------------------------------------------------

app = FastAPI(title="RouteSafe AI Backend", version="0.1")

# CORS: for prototype, allow everything (no cookies)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # wide open for now
    allow_credentials=False,   # MUST be false if origin="*"
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------

class RouteRequest(BaseModel):
    depot_postcode: str
    stops: List[str]
    vehicle_height_m: float


class BridgeOut(BaseModel):
    name: str | None = None
    bridge_height_m: float
    distance_from_start_m: float
    lat: float
    lon: float


class RouteLegOut(BaseModel):
    from_postcode: str
    to_postcode: str
    distance_km: float
    duration_min: float
    vehicle_height_m: float
    low_bridges: List[BridgeOut]


class RouteResponse(BaseModel):
    legs: List[RouteLegOut]


# -------------------------------------------------------------------
# Helper: ORS geocoding
# -------------------------------------------------------------------

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    """
    Geocode a UK postcode using OpenRouteService.

    Returns:
        (lat, lon)
    """
    if not ORS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ORS_API_KEY is not configured on the server.",
        )

    text = postcode.strip().upper()
    if not text:
        raise HTTPException(
            status_code=400, detail="Empty postcode supplied for geocoding."
        )

    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": text,
        "size": 1,
        "boundary.country": "GB",
    }

    try:
        resp = requests.get(url, params=params, timeout=20)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error calling ORS geocoding for '{text}': {exc}",
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=(
                f"ORS geocoding failed for '{text}' "
                f"(status {resp.status_code}): {resp.text[:300]}"
            ),
        )

    data = resp.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(
            status_code=400,
            detail=f"No geocoding result found for postcode '{text}'.",
        )

    coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
    if not isinstance(coords, list) or len(coords) < 2:
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected geocoding response for '{text}': {data}",
        )

    lon, lat = coords[0], coords[1]
    return float(lat), float(lon)


# -------------------------------------------------------------------
# Helper: ORS routing
# -------------------------------------------------------------------

def _extract_summary_from_ors(data: Dict[str, Any], raw_text: str) -> Dict[str, float]:
    """
    ORS can return either:
      - JSON:    { "routes": [ { "summary": {...} } ] }
      - GeoJSON: { "features": [ { "properties": { "summary": {...} } } ] }

    This helper normalises both into {distance_km, duration_min}.
    """
    summary: Dict[str, Any] | None = None

    try:
        if "routes" in data:
            # Standard JSON format
            summary = data["routes"][0]["summary"]
        elif "features" in data:
            # GeoJSON format
            summary = data["features"][0]["properties"]["summary"]
        else:
            raise KeyError("Neither 'routes' nor 'features' present")
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unexpected routing response from ORS: "
                f"{e} | payload: {raw_text[:300]}"
            ),
        )

    distance_km = float(summary["distance"]) / 1000.0
    duration_min = float(summary["duration"]) / 60.0

    return {
        "distance_km": round(distance_km, 2),
        "duration_min": round(duration_min, 1),
    }


def get_hgv_route_metrics(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
) -> Dict[str, float]:
    """
    Call ORS driving-hgv directions and return total distance (km) and
    duration (minutes). If the HGV profile is not available, we fall
    back to driving-car.
    """

    if not ORS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ORS_API_KEY is not configured on the server.",
        )

    def call_ors(profile: str):
        url = f"https://api.openrouteservice.org/v2/directions/{profile}"
        headers = {
            "Authorization": ORS_API_KEY,
            "Content-Type": "application/json",
        }
        body = {
            "coordinates": [
                [start_lon, start_lat],
                [end_lon, end_lat],
            ]
        }
        resp = requests.post(url, json=body, headers=headers, timeout=25)
        return profile, resp

    last_error_txt: str | None = None

    # Try HGV first, then car
    for profile in ["driving-hgv", "driving-car"]:
        profile_used, resp = call_ors(profile)

        if resp.status_code != 200:
            last_error_txt = (
                f"{profile_used} status {resp.status_code}: {resp.text[:300]}"
            )
            continue

        raw_text = resp.text
        data: Dict[str, Any] = resp.json()

        # Normalise JSON/GeoJSON via helper
        return _extract_summary_from_ors(data, raw_text)

    # If both profiles failed:
    raise HTTPException(
        status_code=502,
        detail=f"Routing failed via ORS: {last_error_txt or 'no response'}",
    )


# -------------------------------------------------------------------
# API endpoints
# -------------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "ok", "service": "RouteSafe AI backend"}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/route", response_model=RouteResponse)
def api_route(req: RouteRequest):
    """
    Main entry point for the frontend.

    1. Geocode depot + stops using ORS.
    2. Build legs between consecutive points.
    3. For each leg:
         - Get distance/time from ORS routing.
         - Ask BridgeEngine for low-bridge hazards.
    """

    if not ORS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ORS_API_KEY is not configured on the server.",
        )

    # Normalise input
    depot_pc = req.depot_postcode.strip().upper()
    stops_clean = [s.strip().upper() for s in req.stops if s.strip()]

    if not depot_pc:
        raise HTTPException(
            status_code=400, detail="Depot postcode must not be empty."
        )
    if not stops_clean:
        raise HTTPException(
            status_code=400,
            detail="At least one delivery postcode is required.",
        )
    if req.vehicle_height_m <= 0:
        raise HTTPException(
            status_code=400,
            detail="Vehicle height must be a positive number in metres.",
        )

    # 1) Geocode all points
    points: List[Tuple[float, float]] = []  # (lat, lon)
    postcodes: List[str] = []

    # depot
    depot_lat, depot_lon = geocode_postcode(depot_pc)
    points.append((depot_lat, depot_lon))
    postcodes.append(depot_pc)

    # stops
    for pc in stops_clean:
        lat, lon = geocode_postcode(pc)
        points.append((lat, lon))
        postcodes.append(pc)

    # 2) Build legs
    legs_out: List[Dict[str, Any]] = []

    for idx in range(len(points) - 1):
        start_lat, start_lon = points[idx]
        end_lat, end_lon = points[idx + 1]

        metrics = get_hgv_route_metrics(
            start_lon=start_lon,
            start_lat=start_lat,
            end_lon=end_lon,
            end_lat=end_lat,
        )

        # Find low bridges near this leg
        low_bridges_raw = bridge_engine.find_low_bridges_for_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=req.vehicle_height_m,
        )

        # Normalise bridge objects to simple dicts
        low_bridges: List[Dict[str, Any]] = []
        for b in low_bridges_raw:
            low_bridges.append(
                {
                    "name": b.get("name"),
                    "bridge_height_m": float(b.get("bridge_height_m")),
                    "distance_from_start_m": float(
                        b.get("distance_from_start_m", 0.0)
                    ),
                    "lat": float(b.get("lat")),
                    "lon": float(b.get("lon")),
                }
            )

        leg = {
            "from_postcode": postcodes[idx],
            "to_postcode": postcodes[idx + 1],
            "distance_km": metrics["distance_km"],
            "duration_min": metrics["duration_min"],
            "vehicle_height_m": req.vehicle_height_m,
            "low_bridges": low_bridges,
        }
        legs_out.append(leg)

    return {"legs": legs_out}