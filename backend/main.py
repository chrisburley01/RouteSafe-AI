# backend/main.py
#
# RouteSafe backend v5.1
# - Serves the SPA frontend from the /web folder
# - Exposes /api/route for low-bridge-checked HGV route legs
# - Accepts a flexible JSON body from the frontend without strict validation.
# - If a low bridge is detected, attempts to compute an alternative HGV-safe
#   leg using OpenRouteService with an avoid-polygon around the bridge.

import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlencode, quote_plus

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from bridge_engine import BridgeEngine, BridgeCheckResult, Bridge

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent          # .../backend
WEB_DIR = BASE_DIR.parent / "web"                   # .../web (repo sibling)

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use CSV next to backend/main.py
bridge_engine = BridgeEngine(csv_path=str(BASE_DIR / "bridge_heights_clean.csv"))

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def pick(data: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    """Return the first non-empty key value from a list of possible keys."""
    for k in keys:
        if k in data and data[k] not in ("", None, [], {}):
            return data[k]
    return None


def coerce_delivery_list(raw: Any) -> List[str]:
    """Normalise deliveries to a clean list of postcodes."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        return [s.strip() for s in raw.splitlines() if s.strip()]
    return []


def geocode_postcode(postcode: str) -> Tuple[float, float]:
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
) -> Tuple[float, float]:
    """Basic ORS HGV route between A and B (no avoid-polygon)."""
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


def fetch_alt_summary_avoiding_bridge(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    bridge: Bridge,
) -> Optional[Tuple[float, float]]:
    """
    Try to get an alternative HGV route that avoids a small box around the bridge.

    Returns (distance_km, duration_min) if successful, otherwise None.
    """
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}

    # Build a tiny square "no-go" polygon around the bridge.
    # Roughly ~200m box – good enough at UK latitudes for a prototype.
    delta = 0.002  # ~200m in degrees
    min_lon = bridge.lon - delta
    max_lon = bridge.lon + delta
    min_lat = bridge.lat - delta
    max_lat = bridge.lat + delta

    avoid_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]
        ],
    }

    payload = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
        "options": {"avoid_polygons": avoid_polygon},
    }

    r = requests.post(ORS_DIRECTIONS_URL, json=payload, headers=headers, timeout=15)
    if r.status_code != 200:
        # If ORS can't find an alt route, just skip alt instead of failing the whole leg.
        print("DEBUG alt route failed:", r.status_code, r.text)
        return None

    try:
        data = r.json()
        route = data["routes"][0]
        summary = route["summary"]
        distance_km = summary["distance"] / 1000.0
        duration_min = summary["duration"] / 60.0
    except Exception as e:
        print("DEBUG alt route parse error:", e)
        return None

    return distance_km, duration_min


def build_bridge_message(check: BridgeCheckResult) -> str:
    if check.has_conflict:
        return (
            "⚠️ Low bridge on this leg. Route not HGV safe at current height. "
            "Direct route only – see the alternative suggested route card below."
        )
    if check.near_height_limit:
        return "⚠️ Bridges close to your vehicle height – double-check before travelling."
    if check.nearest_bridge is None:
        return "No low bridges on this leg."
    return "No low bridges within the risk radius for this leg."


def build_safety_label(check: BridgeCheckResult) -> str:
    # Never call something HGV SAFE if there is any conflict
    if check.has_conflict:
        return "LOW BRIDGE RISK"
    if check.near_height_limit:
        return "CHECK HEIGHT"
    return "HGV SAFE"


def build_google_maps_url(
    start_postcode: str,
    end_postcode: str,
    bridge: Optional[Bridge],
) -> str:
    """
    Build a Google Maps deep link.

    For now, we always route origin -> destination; if a bridge is present we
    add it as a waypoint so the pin is visible. (This is for DRIVER AWARENESS.
    Google may still choose its own path; ORS is the safety engine.)
    """
    origin = quote_plus(start_postcode)
    destination = quote_plus(end_postcode)

    params = {"api": "1", "origin": origin, "destination": destination}

    if bridge is not None:
        waypoints = f"{bridge.lat},{bridge.lon}"
        params["waypoints"] = waypoints

    return "https://www.google.com/maps/dir/?" + urlencode(params, safe="|,")


# ---------------------------------------------------------------------------
# API route – simple dict body (no 422s)
# ---------------------------------------------------------------------------


@app.post("/api/route")
async def generate_route(body: Dict[str, Any]):
    """
    Accepts a flexible JSON body so old/new frontends work:

    - vehicleHeight OR vehicle_height_m OR height
    - originPostcode OR origin_postcode OR depotPostcode OR startPostcode
    - deliveryPostcodes OR delivery_postcodes OR postcodes OR drops
    """
    data = body or {}

    # Debug log (shows in Render logs)
    print("DEBUG incoming payload:", data)

    # vehicle height
    vh = pick(
        data,
        ["vehicleHeight", "vehicle_height_m", "vehicle_height", "height", "hgv_height"],
    )
    if vh is None:
        return {"error": "vehicle height is required", "legs": []}
    try:
        vehicle_height = float(vh)
    except ValueError:
        return {"error": "vehicle height must be a number", "legs": []}

    # origin / depot
    origin = pick(
        data,
        [
            "originPostcode",
            "origin_postcode",
            "depotPostcode",
            "depot_postcode",
            "startPostcode",
            "start_postcode",
        ],
    )
    if not origin:
        return {"error": "depot/origin postcode is required", "legs": []}
    origin = str(origin).strip()

    # deliveries
    raw_deliveries = pick(
        data,
        ["deliveryPostcodes", "delivery_postcodes", "postcodes", "drops"],
    )
    delivery_postcodes = coerce_delivery_list(raw_deliveries)
    if not delivery_postcodes:
        return {"error": "at least one delivery postcode is required", "legs": []}

    stops = [origin] + delivery_postcodes
    legs: List[Dict[str, Any]] = []

    for i in range(len(stops) - 1):
        start_pc = stops[i]
        end_pc = stops[i + 1]

        # Geocode
        try:
            start_lat, start_lon = geocode_postcode(start_pc)
            end_lat, end_lon = geocode_postcode(end_pc)
        except HTTPException as e:
            legs.append(
                {
                    "index": i + 1,
                    "start_postcode": start_pc,
                    "end_postcode": end_pc,
                    "error": e.detail,
                }
            )
            continue

        # ORS routing – direct leg
        try:
            distance_km, duration_min = fetch_leg_summary(
                start_lat, start_lon, end_lat, end_lon
            )
        except HTTPException as e:
            legs.append(
                {
                    "index": i + 1,
                    "start_postcode": start_pc,
                    "end_postcode": end_pc,
                    "error": e.detail,
                }
            )
            continue

        # Bridge check (RouteSafe engine)
        check: BridgeCheckResult = bridge_engine.check_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=vehicle_height,
        )

        nearest: Optional[Bridge] = check.nearest_bridge

        leg: Dict[str, Any] = {
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
            "google_maps_url": build_google_maps_url(start_pc, end_pc, nearest),
            "bridge_points": []
            if nearest is None
            else [
                {
                    "lat": nearest.lat,
                    "lon": nearest.lon,
                    "height_m": nearest.height_m,
                }
            ],
        }

        # If this leg has a low bridge and we have a coordinate, try to compute
        # an alternative HGV-safe route that avoids the bridge area.
        if check.has_conflict and nearest is not None:
            alt_summary = fetch_alt_summary_avoiding_bridge(
                start_lat=start_lat,
                start_lon=start_lon,
                end_lat=end_lat,
                end_lon=end_lon,
                bridge=nearest,
            )
            if alt_summary is not None:
                alt_distance_km, alt_duration_min = alt_summary

                # Main alt fields
                leg["alt_distance_km"] = round(alt_distance_km, 1)
                leg["alt_duration_min"] = round(alt_duration_min, 1)
                # For now we still point to the same origin/destination map link;
                # ORS is the safety engine, Maps is just for navigation.
                alt_maps_url = build_google_maps_url(start_pc, end_pc, None)
                leg["alt_maps_url"] = alt_maps_url

                # Backwards-compatibility keys for older JS
                leg["alt_google_maps_url"] = alt_maps_url
                leg["alt_distance"] = round(alt_distance_km, 1)
                leg["alt_time"] = round(alt_duration_min, 1)

        legs.append(leg)

    return {"legs": legs}


# ---------------------------------------------------------------------------
# Static frontend mount at "/"
# ---------------------------------------------------------------------------

if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:

    @app.get("/")
    def root():
        return {
            "detail": "RouteSafe API is running, but /web folder was not found next to backend/."
        }