# backend/main.py
#
# RouteSafe backend:
# - Serves the SPA frontend from the /web folder
# - Exposes /api/route for low-bridge-checked HGV route legs
# - NO Pydantic validation on input to avoid 422 errors.

import os
from pathlib import Path
from typing import List, Dict, Any
from urllib.parse import urlencode, quote_plus

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from bridge_engine import BridgeEngine, BridgeCheckResult, Bridge

# ---------------------------------------------------------------------------
# Paths: find /web whether the service root is repo/ or repo/backend/
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent          # usually .../backend
WEB_CANDIDATES = [
    BASE_DIR / "web",          # if web is inside backend/
    BASE_DIR.parent / "web",   # if web is a sibling: repo/web
]

WEB_DIR = None
for c in WEB_CANDIDATES:
    if c.is_dir():
        WEB_DIR = c
        break

if WEB_DIR is None:
    WEB_DIR = BASE_DIR  # fallback – but you *do* have /web so this shouldn't happen

# ---------------------------------------------------------------------------
# External services config
# ---------------------------------------------------------------------------

ORS_API_KEY = os.getenv("ORS_API_KEY")
if not ORS_API_KEY:
    raise RuntimeError("Please set ORS_API_KEY in your environment.")

ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-hgv"
ORS_GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="RouteSafe HGV Low-Bridge Checker")

# ✅ Correct pattern: pass the CLASS + kwargs, not an instance
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bridge_engine = BridgeEngine()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def geocode_postcode(postcode: str) -> (float, float):
    params = {
        "api_key": ORS_API_KEY,
        "text": postcode,
        "boundary.country": "GB",
        "size": 1,
    }
    r = requests.get(ORS_GEOCODE_URL, params=params, timeout=10)
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Geocoding failed for {postcode}: {r.text}",
        )

    data = r.json()
    features = data.get("features", [])
    if not features:
        raise HTTPException(
            status_code=404, detail=f"Postcode not found: {postcode}"
        )

    coords = features[0]["geometry"]["coordinates"]
    lon, lat = float(coords[0]), float(coords[1])
    return lat, lon


def fetch_leg_summary(
    start_lat: float, start_lon: float, end_lat: float, end_lon: float
) -> (float, float):
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    payload = {"coordinates": [[start_lon, start_lat], [end_lon, end_lat]]}

    r = requests.post(ORS_DIRECTIONS_URL, json=payload, headers=headers, timeout=15)
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Routing failed: {r.text}",
        )

    data = r.json()
    route = data["routes"][0]
    summary = route["summary"]
    distance_km = summary["distance"] / 1000.0
    duration_min = summary["duration"] / 60.0
    return distance_km, duration_min


def build_bridge_message(check: BridgeCheckResult) -> str:
    if check.has_conflict:
        return "⚠️ Low bridge on this leg. Route not HGV safe at current height."
    if check.near_height_limit:
        return "⚠️ Bridges close to your vehicle height – double-check before travelling."
    if check.nearest_bridge is None:
        return "No low bridges on this leg."
    return "No low bridges within the risk radius for this leg."


def build_safety_label(check: BridgeCheckResult) -> str:
    if check.has_conflict:
        return "LOW BRIDGE RISK"
    if check.near_height_limit:
        return "CHECK HEIGHT"
    return "HGV SAFE"


def build_google_maps_url(
    start_postcode: str,
    end_postcode: str,
    bridges: List[Bridge],
) -> str:
    origin = quote_plus(start_postcode)
    destination = quote_plus(end_postcode)

    params = {"api": "1", "origin": origin, "destination": destination}

    if bridges:
        waypoints = "|".join(f"{b.lat},{b.lon}" for b in bridges)
        params["waypoints"] = waypoints

    return "https://www.google.com/maps/dir/?" + urlencode(params, safe="|,")


def coerce_delivery_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        return [s.strip() for s in raw.splitlines() if s.strip()]
    return []


# ---------------------------------------------------------------------------
# API route – NO Pydantic on input, so 422 can't happen
# ---------------------------------------------------------------------------


@app.post("/api/route")
async def generate_route(request: Request):
    """
    Very forgiving endpoint – it will accept any JSON shape and try to
    interpret it as a RouteSafe request.

    Expected keys (any of these variations are accepted):
      - vehicleHeight OR vehicle_height_m
      - depotPostcode OR originPostcode OR startPostcode
      - deliveryPostcodes OR postcodes OR stops
    """
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        payload = {}

    # vehicle height
    vh = (
        payload.get("vehicleHeight")
        or payload.get("vehicle_height_m")
        or payload.get("vehicleHeightM")
    )
    if vh is None:
        raise HTTPException(status_code=400, detail="vehicle height is required")
    try:
        vehicle_height = float(vh)
    except ValueError:
        raise HTTPException(status_code=400, detail="vehicle height must be a number")

    # depot / origin
    depot = (
        payload.get("depotPostcode")
        or payload.get("originPostcode")
        or payload.get("startPostcode")
    )
    if not depot or not str(depot).strip():
        raise HTTPException(status_code=400, detail="depot/origin postcode is required")
    depot_postcode = str(depot).strip()

    # deliveries
    raw_deliveries = (
        payload.get("deliveryPostcodes")
        or payload.get("postcodes")
        or payload.get("stops")
    )
    delivery_postcodes = coerce_delivery_list(raw_deliveries)
    if not delivery_postcodes:
        raise HTTPException(
            status_code=400, detail="At least one delivery postcode is required"
        )

    stops = [depot_postcode] + delivery_postcodes
    legs: List[Dict[str, Any]] = []

    for i in range(len(stops) - 1):
        start_pc = stops[i]
        end_pc = stops[i + 1]

        start_lat, start_lon = geocode_postcode(start_pc)
        end_lat, end_lon = geocode_postcode(end_pc)

        distance_km, duration_min = fetch_leg_summary(
            start_lat, start_lon, end_lat, end_lon
        )

        check = bridge_engine.check_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=vehicle_height,
        )

        bridge_list = (
            check.conflict_bridges if check.conflict_bridges else check.near_bridges
        )

        gm_url = build_google_maps_url(
            start_postcode=start_pc,
            end_postcode=end_pc,
            bridges=bridge_list,
        )

        leg = {
            "index": i + 1,
            "start_postcode": start_pc,
            "end_postcode": end_pc,
            "distance_km": round(distance_km, 1),
            "duration_min": round(duration_min, 1),
            "vehicle_height_m": vehicle_height,
            "has_conflict": check.has_conflict,
            "near_height_limit": check.near_height_limit,
            "bridge_message": build_bridge_message(check),
            "safety_label": build_safety_label(check),
            "google_maps_url": gm_url,
            "bridge_points": [
                {"lat": b.lat, "lon": b.lon, "height_m": b.height_m}
                for b in bridge_list
            ],
        }
        legs.append(leg)

    # Plain dict – no response validation
    return {"legs": legs}


# ---------------------------------------------------------------------------
# Static frontend mount: serve /web at "/"
# ---------------------------------------------------------------------------

app.mount(
    "/",
    StaticFiles(directory=str(WEB_DIR), html=True),
    name="web",
)