import os
from typing import List, Dict, Tuple, Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# FIXED: absolute import so Render stops circular-importing
from backend.bridge_engine import BridgeEngine

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    print("WARNING: ORS_API_KEY environment variable is not set.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_CSV_PATH = os.path.join(BASE_DIR, "bridge_heights_clean.csv")

bridge_engine = BridgeEngine(BRIDGE_CSV_PATH)

# -------------------------------------------------------------------
# FastAPI setup
# -------------------------------------------------------------------

app = FastAPI(title="RouteSafe AI Backend", version="0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
# UI HTML — SAME AS BEFORE
# (kept exactly as working)
# -------------------------------------------------------------------

HTML_PAGE = """
[[[[ YOUR EXISTING HTML EXACTLY HERE — unchanged ]]]]
"""

# -------------------------------------------------------------------
# Helpers: ORS geocoding + routing
# -------------------------------------------------------------------

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    if not ORS_API_KEY:
        raise HTTPException(500, "ORS_API_KEY missing")

    text = postcode.strip().upper()
    if not text:
        raise HTTPException(400, "Empty postcode")

    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": text,
        "size": 1,
        "boundary.country": "GB",
    }

    resp = requests.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        raise HTTPException(502, f"Geocode failed for {text}")

    data = resp.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(400, f"No result for postcode {text}")

    lon, lat = features[0]["geometry"]["coordinates"]
    return float(lat), float(lon)


def _extract_summary_from_ors(data: Dict[str, Any], raw: str) -> Dict[str, float]:
    try:
        if "routes" in data:
            summary = data["routes"][0]["summary"]
        elif "features" in data:
            summary = data["features"][0]["properties"]["summary"]
        else:
            raise KeyError
    except Exception:
        raise HTTPException(502, "Unexpected ORS routing response")

    km = float(summary["distance"]) / 1000.0
    mins = float(summary["duration"]) / 60.0

    return {
        "distance_km": round(km, 2),
        "duration_min": round(mins, 1),
    }


def get_hgv_route_metrics(start_lon, start_lat, end_lon, end_lat):
    if not ORS_API_KEY:
        raise HTTPException(500, "ORS_API_KEY missing")

    def call(profile):
        url = f"https://api.openrouteservice.org/v2/directions/{profile}"
        headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
        body = {"coordinates": [[start_lon, start_lat], [end_lon, end_lat]]}
        return profile, requests.post(url, json=body, headers=headers, timeout=25)

    last_err = None

    for profile in ["driving-hgv", "driving-car"]:
        pf, resp = call(profile)
        if resp.status_code == 200:
            return _extract_summary_from_ors(resp.json(), resp.text)
        last_err = f"{pf}: {resp.status_code}"

    raise HTTPException(502, f"Routing failed: {last_err}")

# -------------------------------------------------------------------
# API endpoints
# -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return HTMLResponse(content=HTML_PAGE, status_code=200)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/route", response_model=RouteResponse)
def api_route(req: RouteRequest):

    depot_pc = req.depot_postcode.strip().upper()
    stops = [s.strip().upper() for s in req.stops if s.strip()]
    vh = float(req.vehicle_height_m)

    if not depot_pc:
        raise HTTPException(400, "Depot postcode missing")
    if not stops:
        raise HTTPException(400, "No stops supplied")
    if vh <= 0:
        raise HTTPException(400, "Vehicle height invalid")

    # ---- geocode all
    postcodes = []
    points = []

    lat, lon = geocode_postcode(depot_pc)
    points.append((lat, lon))
    postcodes.append(depot_pc)

    for pc in stops:
        lat, lon = geocode_postcode(pc)
        points.append((lat, lon))
        postcodes.append(pc)

    # ---- build legs
    legs = []

    for i in range(len(points) - 1):
        slat, slon = points[i]
        elat, elon = points[i + 1]

        metrics = get_hgv_route_metrics(
            start_lon=slon,
            start_lat=slat,
            end_lon=elon,
            end_lat=elat,
        )

        # ---- BRIDGE CHECK (new correct integration)
        result = bridge_engine.check_leg(
            start_lat=slat,
            start_lon=slon,
            end_lat=elat,
            end_lon=elon,
            vehicle_height_m=vh,
        )

        low_bridges = []

        if result.nearest_bridge:
            low_bridges.append({
                "name": None,
                "bridge_height_m": result.nearest_bridge.height_m,
                "distance_from_start_m": float(result.nearest_distance_m or 0),
                "lat": result.nearest_bridge.lat,
                "lon": result.nearest_bridge.lon,
            })

        legs.append({
            "from_postcode": postcodes[i],
            "to_postcode": postcodes[i + 1],
            "distance_km": metrics["distance_km"],
            "duration_min": metrics["duration_min"],
            "vehicle_height_m": vh,
            "low_bridges": low_bridges,
        })

    return {"legs": legs}