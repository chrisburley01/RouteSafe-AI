from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Tuple
import os
import re
import requests

from bridge_engine import BridgeEngine, BridgeCheckResult

# ------------------------------------------------------------
# Config
# ------------------------------------------------------------
ORS_API_KEY = os.getenv("ORS_API_KEY")

app = FastAPI(
    title="RouteSafe-AI",
    version="5.1-restore",
    description="HGV low-bridge routing engine – ORS + UK bridge data",
)

# Single BridgeEngine instance (loads CSV once on startup)
bridge_engine = BridgeEngine(csv_path="bridge_heights_clean.csv")


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def normalise_uk_postcode(value: str) -> str:
    """
    Normalise things like 'LS270BN' or 'ls27 0bn' -> 'LS27 0BN'.
    If it doesn't look like a UK postcode, just trim whitespace.
    """
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if not (5 <= len(raw) <= 7):
        return value.strip()
    return f"{raw[:-3]} {raw[-3:]}"


def format_distance(meters: Optional[float]) -> str:
    if meters is None:
        return "-"
    if meters < 1000:
        return f"{meters:.0f} m"
    km = meters / 1000.0
    return f"{km:.1f} km"


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    mins, _ = divmod(rem, 60)
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins} min"


# ------------------------------------------------------------
# Request model
# ------------------------------------------------------------
class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ------------------------------------------------------------
# ORS helpers
# ------------------------------------------------------------
def geocode_address(query: str) -> Tuple[float, float]:
    """
    Geocode using ORS.
    Returns (lon, lat).
    """
    if not ORS_API_KEY:
        raise HTTPException(status_code=500, detail="ORS_API_KEY missing on server")

    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query}

    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"ORS geocode failed: {query}")

    data = r.json()
    if not data.get("features"):
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {query}")

    coords = data["features"][0]["geometry"]["coordinates"]
    return coords[0], coords[1]  # lon, lat


def fetch_route_geojson(start_lon: float, start_lat: float,
                        end_lon: float, end_lat: float) -> dict:
    """
    Call ORS directions (HGV profile) and return full GeoJSON feature collection.

    IMPORTANT: uses the /geojson endpoint.
    No `geometry_format`, no `polyline` library – ORS gives us raw coordinates.
    """
    if not ORS_API_KEY:
        raise HTTPException(status_code=500, detail="ORS_API_KEY missing on server")

    url = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ]
    }
    params = {"api_key": ORS_API_KEY}

    r = requests.post(url, json=body, params=params, timeout=40)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"ORS routing failed: {r.text}")

    return r.json()


# ------------------------------------------------------------
# Bridge analysis over the route coordinates
# ------------------------------------------------------------
def analyse_bridges_along_route(
    coords: List[List[float]], vehicle_height_m: float
) -> dict:
    """
    Run the BridgeEngine over each leg of the route.
    coords: list of [lon, lat]
    """
    has_conflict = False
    near_height = False
    nearest_bridge = None
    nearest_distance_m = None
    warnings: List[str] = []

    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]

        # BridgeEngine takes (lat, lon)
        result: BridgeCheckResult = bridge_engine.check_leg(
            (lat1, lon1),
            (lat2, lon2),
            vehicle_height_m=vehicle_height_m,
        )

        if result.nearest_bridge:
            d = result.nearest_distance_m or 0.0
            if nearest_distance_m is None or d < nearest_distance_m:
                nearest_distance_m = d
                nearest_bridge = result.nearest_bridge

        if result.has_conflict:
            has_conflict = True
            if result.nearest_bridge and result.nearest_distance_m is not None:
                warnings.append(
                    f"Low bridge conflict near "
                    f"({result.nearest_bridge.lat:.5f}, {result.nearest_bridge.lon:.5f}) "
                    f"height {result.nearest_bridge.height_m:.2f} m "
                    f"within {result.nearest_distance_m:.0f} m of route."
                )
        elif result.near_height_limit:
            near_height = True
            if result.nearest_bridge and result.nearest_distance_m is not None:
                warnings.append(
                    f"Bridge near height limit "
                    f"({result.nearest_bridge.height_m:.2f} m) "
                    f"within {result.nearest_distance_m:.0f} m of route at "
                    f"({result.nearest_bridge.lat:.5f}, {result.nearest_bridge.lon:.5f})."
                )

    if has_conflict:
        risk_level = "high"
        risk_badge = "High risk"
        risk_text = "Low-bridge conflicts detected on this route."
    elif near_height:
        risk_level = "medium"
        risk_badge = "Medium risk"
        risk_text = "Route passes close to bridges near your vehicle height."
    else:
        risk_level = "low"
        risk_badge = "Low risk"
        risk_text = "No low-bridge conflicts detected based on current data."

    if nearest_bridge and nearest_distance_m is not None:
        nearest_bridge_text = (
            f"{nearest_bridge.height_m:.2f} m bridge approx "
            f"{nearest_distance_m:.0f} m from route."
        )
    else:
        nearest_bridge_text = "None on route"

    return {
        "risk_level": risk_level,
        "risk_badge": risk_badge,
        "risk_text": risk_text,
        "nearest_bridge_text": nearest_bridge_text,
        "warnings": warnings,
    }


# ------------------------------------------------------------
# API route
# ------------------------------------------------------------
@app.post("/api/route")
def create_route(req: RouteRequest):
    # 1) Clean / normalise postcodes
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) Geocode both ends
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) Get ORS route as GeoJSON
    route_geojson = fetch_route_geojson(start_lon, start_lat, end_lon, end_lat)

    features = route_geojson.get("features") or []
    if not features:
        raise HTTPException(status_code=400, detail="No route returned from ORS.")

    feature0 = features[0]
    geometry = feature0.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if not coords:
        raise HTTPException(status_code=400, detail="Route geometry missing from ORS.")

    props = feature0.get("properties") or {}
    summary = props.get("summary") or {}
    distance_m = summary.get("distance")
    duration_s = summary.get("duration")

    # 4) Bridge risk analysis (if enabled)
    if req.avoid_low_bridges:
        bridge_info = analyse_bridges_along_route(coords, req.vehicle_height_m)
    else:
        bridge_info = {
            "risk_level": "unknown",
            "risk_badge": "Not checked",
            "risk_text": "Low-bridge analysis disabled for this request.",
            "nearest_bridge_text": "Not checked",
            "warnings": [],
        }

    # 5) Simple per-step summary for front end (optional)
    steps_out: List[dict] = []
    segments = props.get("segments") or []
    if segments:
        seg0 = segments[0]
        for step in seg0.get("steps", []):
            steps_out.append(
                {
                    "instruction": step.get("instruction", ""),
                    "distance_text": format_distance(step.get("distance")),
                }
            )

    return {
        "ok": True,
        "start_used": start_query,
        "end_used": end_query,
        "distance_text": format_distance(distance_m),
        "duration_text": format_duration(duration_s),
        "risk_level": bridge_info["risk_level"],
        "risk_badge": bridge_info["risk_badge"],
        "risk_text": bridge_info["risk_text"],
        "nearest_bridge_text": bridge_info["nearest_bridge_text"],
        "warnings": bridge_info["warnings"],
        "steps": steps_out,
        "route_geojson": route_geojson,
    }


# ------------------------------------------------------------
# Health check
# ------------------------------------------------------------
@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route",
        "version": "5.1-restore",
    }