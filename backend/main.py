# ===========================
# RouteSafe-AI Backend v5.2
# HGV routing + low-bridge engine
# ===========================
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import os
import re
from typing import List, Dict, Any, Optional

from bridge_engine import BridgeEngine, BridgeCheckResult

# ORS API key from environment
ORS_API_KEY = os.getenv("ORS_API_KEY")
if not ORS_API_KEY:
    raise RuntimeError("ORS_API_KEY environment variable is not set")

# Instantiate bridge engine (CSV in same folder)
BRIDGE_ENGINE = BridgeEngine(csv_path="bridge_heights_clean.csv")

app = FastAPI(
    title="RouteSafe-AI",
    version="5.2",
    description="HGV low-bridge routing engine – avoid low bridges"
)

# Allow Navigator frontend (and others) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can restrict later if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# UK POSTCODE NORMALISER
# ------------------------------------------------------------
def normalise_uk_postcode(value: str) -> str:
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    # Only normalise plausible UK postcode lengths
    if not (5 <= len(raw) <= 7):
        return value.strip()

    return f"{raw[:-3]} {raw[-3:]}"


# ------------------------------------------------------------
# Request model – matches Navigator
# ------------------------------------------------------------
class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ------------------------------------------------------------
# Helper: ORS geocoding
# ------------------------------------------------------------
def geocode_address(query: str):
    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": query,
        "size": 1,
    }

    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"ORS geocode failed: {query}")

    data = r.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {query}")

    coords = features[0]["geometry"]["coordinates"]
    lon, lat = coords[0], coords[1]
    return lon, lat


# ------------------------------------------------------------
# Helper: ORS HGV route
# ------------------------------------------------------------
def ors_hgv_route(start_lon: float, start_lat: float,
                  end_lon: float, end_lat: float) -> Dict[str, Any]:
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat]
        ],
        "instructions": True,
        "elevation": False,
    }

    r = requests.post(url, json=body, headers=headers, timeout=40)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"ORS routing failed: {r.text}")

    data = r.json()
    routes = data.get("features") or []
    if not routes:
        raise HTTPException(status_code=400, detail="No route returned from ORS")

    feat = routes[0]
    props = feat["properties"]
    geom = feat["geometry"]

    summary = props.get("summary", {})
    distance_m = summary.get("distance", 0.0)
    duration_s = summary.get("duration", 0.0)

    # ORS uses [lon, lat]
    coords = geom.get("coordinates", [])
    coord_latlon = [[c[1], c[0]] for c in coords]

    # Steps (for future turn-by-turn use)
    steps: List[Dict[str, Any]] = []
    segments = props.get("segments") or []
    if segments:
        for seg in segments:
            for st in seg.get("steps", []):
                steps.append({
                    "instruction": st.get("instruction"),
                    "distance_m": st.get("distance"),
                    "duration_s": st.get("duration"),
                })

    return {
        "distance_m": distance_m,
        "duration_s": duration_s,
        "coords_latlon": coord_latlon,
        "steps": steps,
    }


# ------------------------------------------------------------
# Helper: analyse route with bridge engine
# ------------------------------------------------------------
def analyse_route_with_bridges(
    coords_latlon: List[List[float]],
    vehicle_height_m: float,
    avoid_low_bridges: bool
):
    """
    Walk along the route and use BridgeEngine to check each leg.
    coords_latlon = [[lat, lon], ...]
    """
    if len(coords_latlon) < 2:
        return {
            "bridge_risk": "unknown",
            "bridge_summary": "Route too short to analyse.",
            "warnings": [],
            "nearest_bridge": None,
        }

    has_conflict = False
    near_limit = False
    nearest_bridge: Optional[Dict[str, float]] = None
    warnings: List[str] = []

    # To keep things reasonably fast, we can sample every Nth point
    # but for now we'll just iterate everything; ORS routes are usually manageable.
    for i in range(len(coords_latlon) - 1):
        lat1, lon1 = coords_latlon[i]
        lat2, lon2 = coords_latlon[i + 1]

        res: BridgeCheckResult = BRIDGE_ENGINE.check_leg(
            start_lat=lat1,
            start_lon=lon1,
            end_lat=lat2,
            end_lon=lon2,
            vehicle_height_m=vehicle_height_m
        )

        if res.nearest_bridge is not None:
            # Track global nearest bridge
            if nearest_bridge is None or (
                res.nearest_distance_m is not None
                and res.nearest_distance_m < nearest_bridge["distance_m"]
            ):
                nearest_bridge = {
                    "lat": res.nearest_bridge.lat,
                    "lon": res.nearest_bridge.lon,
                    "height_m": res.nearest_bridge.height_m,
                    "distance_m": res.nearest_distance_m,
                }

        if res.has_conflict:
            has_conflict = True
            if res.nearest_bridge is not None:
                warnings.append(
                    f"LOW BRIDGE {res.nearest_bridge.height_m:.2f} m "
                    f"within {res.nearest_distance_m:.0f} m of route."
                )
            else:
                warnings.append("Potential low-bridge conflict on this leg.")

        elif res.near_height_limit:
            near_limit = True
            if res.nearest_bridge is not None:
                warnings.append(
                    f"Bridge {res.nearest_bridge.height_m:.2f} m "
                    f"within {res.nearest_distance_m:.0f} m – close to vehicle height."
                )

    if has_conflict:
        bridge_risk = "high"
        summary = "Low-bridge conflicts detected on route."
    elif near_limit:
        bridge_risk = "medium"
        summary = "No direct conflicts, but some bridges are close to vehicle height."
    else:
        bridge_risk = "low"
        summary = "No low-bridge conflicts detected."

    # If user unticks "avoid low bridges", we still SHOW the risk,
    # just don't alter the route here (routing logic can be enhanced later).
    return {
        "bridge_risk": bridge_risk,
        "bridge_summary": summary,
        "warnings": warnings,
        "nearest_bridge": nearest_bridge,
    }


# ------------------------------------------------------------
# MAIN ROUTE ENDPOINT
# ------------------------------------------------------------
@app.post("/api/route")
def create_route(req: RouteRequest):
    # 1) Normalise postcodes
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) Geocode
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) ORS HGV route
    route_data = ors_hgv_route(start_lon, start_lat, end_lon, end_lat)

    # 4) Bridge analysis
    bridge_data = analyse_route_with_bridges(
        coords_latlon=route_data["coords_latlon"],
        vehicle_height_m=req.vehicle_height_m,
        avoid_low_bridges=req.avoid_low_bridges,
    )

    # 5) Build response for Navigator
    total_distance_km = route_data["distance_m"] / 1000.0 if route_data["distance_m"] else None
    total_duration_min = route_data["duration_s"] / 60.0 if route_data["duration_s"] else None

    return {
        "ok": True,
        "start_used": start_query,
        "end_used": end_query,
        "total_distance_km": total_distance_km,
        "total_duration_min": total_duration_min,
        "bridge_risk": bridge_data["bridge_risk"],
        "bridge_summary": bridge_data["bridge_summary"],
        "nearest_bridge": bridge_data["nearest_bridge"],
        "warnings": bridge_data["warnings"],
        "route_coords": route_data["coords_latlon"],
        "steps": route_data["steps"],
    }


# ------------------------------------------------------------
# Base endpoint – health check
# ------------------------------------------------------------
@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine – POST /api/route for routes",
    }