"""
RouteSafe-AI backend for RouteSafe Navigator v1.0

- POST /api/route
  Request:
    {
      "start": "LS27 0BN",
      "end": "M31 4QN",
      "vehicle_height_m": 5.0,
      "avoid_low_bridges": true
    }

  Response (simplified shape):
    {
      "summary": {...},
      "bridge_risk": {...},
      "warnings": [...],
      "bridges": [...],
      "steps": [...],
      "main_geojson": {...},      # GeoJSON LineString
      "alt_geojson": null         # reserved for future
    }
"""

from typing import List, Optional

import math
import os

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from bridge_engine import BridgeEngine, BridgeCheckResult, Bridge  # uses your CSV


# ------------------------------------------------------
# Config
# ------------------------------------------------------

OSRM_BASE_URL = "https://router.project-osrm.org"

bridge_engine = BridgeEngine(
    csv_path="bridge_heights_clean.csv",
    search_radius_m=300.0,
    conflict_clearance_m=0.0,
    near_clearance_m=0.25,
)

app = FastAPI(
    title="RouteSafe AI – HGV Low-Bridge Engine",
    description="Backend API powering RouteSafe Navigator v1.0",
    version="1.0.0",
)

# CORS so the Navigator frontend can call us
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can later lock this down
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------
# Models
# ------------------------------------------------------

class RouteRequest(BaseModel):
    start: str = Field(..., description="Start postcode or address")
    end: str = Field(..., description="End postcode or address")
    vehicle_height_m: float = Field(..., gt=0, description="Full running height (m)")
    avoid_low_bridges: bool = Field(True, description="If true, try to avoid low bridges")


class BridgeMarker(BaseModel):
    lat: float
    lon: float
    height_m: float
    message: str


class BridgeRiskSummary(BaseModel):
    level: str           # low / medium / high
    status_text: str
    nearest_bridge_height_m: Optional[float] = None
    nearest_bridge_distance_m: Optional[float] = None


class RouteSummary(BaseModel):
    distance_km: float
    duration_min: float


class RouteResponse(BaseModel):
    summary: RouteSummary
    bridge_risk: BridgeRiskSummary
    warnings: List[str]
    bridges: List[BridgeMarker]
    steps: List[str]
    main_geojson: dict
    alt_geojson: Optional[dict] = None


# ------------------------------------------------------
# Simple geocoder using Nominatim (no API key needed)
# ------------------------------------------------------

def geocode(text: str) -> (float, float):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": text,
        "format": "json",
        "limit": 1,
    }
    headers = {
        "User-Agent": "RouteSafe-AI/1.0 (route planning demo)"
    }
    r = requests.get(url, params=params, headers=headers, timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Geocoding failed")
    data = r.json()
    if not data:
        raise HTTPException(status_code=400, detail=f"Could not geocode: {text}")
    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return lat, lon


# ------------------------------------------------------
# Routing via OSRM demo server
# ------------------------------------------------------

def get_route(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    # OSRM wants lon,lat order
    coords = f"{lon1},{lat1};{lon2},{lat2}"
    url = f"{OSRM_BASE_URL}/route/v1/driving/{coords}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "true",
    }
    r = requests.get(url, params=params, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Routing engine error")
    data = r.json()
    if "routes" not in data or not data["routes"]:
        raise HTTPException(status_code=400, detail="No route found")
    return data["routes"][0]


# ------------------------------------------------------
# Bridge risk aggregation
# ------------------------------------------------------

def analyse_bridges(
    coords: List[List[float]], vehicle_height_m: float
) -> (BridgeRiskSummary, List[BridgeMarker], List[str]):
    """
    coords: list of [lon, lat]
    """
    warnings: List[str] = []
    markers: List[BridgeMarker] = []

    any_conflict = False
    any_near = False
    nearest_bridge: Optional[Bridge] = None
    nearest_dist: Optional[float] = None

    # Walk along each leg of the geometry
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]

        result: BridgeCheckResult = bridge_engine.check_leg(
            lat1, lon1, lat2, lon2, vehicle_height_m
        )

        if result.nearest_bridge and result.nearest_distance_m is not None:
            b = result.nearest_bridge
            markers.append(
                BridgeMarker(
                    lat=b.lat,
                    lon=b.lon,
                    height_m=b.height_m,
                    message=f"Bridge {b.height_m:.2f}m at {result.nearest_distance_m:.0f}m from leg",
                )
            )

            if nearest_dist is None or result.nearest_distance_m < nearest_dist:
                nearest_dist = result.nearest_distance_m
                nearest_bridge = b

        if result.has_conflict:
            any_conflict = True
            warnings.append(
                "Route passes a bridge LOWER than your vehicle height. "
                "This leg is NOT safe without a diversion."
            )
        elif result.near_height_limit:
            any_near = True
            warnings.append(
                "Route passes close to a bridge near your height. Extra caution required."
            )

    if any_conflict:
        level = "high"
        status_text = "High risk: at least one bridge is too low for this vehicle."
    elif any_near:
        level = "medium"
        status_text = "Medium risk: some bridges are close to the vehicle height."
    else:
        level = "low"
        status_text = "Low bridge risk on this route based on known data."

    risk = BridgeRiskSummary(
        level=level,
        status_text=status_text,
        nearest_bridge_height_m=nearest_bridge.height_m if nearest_bridge else None,
        nearest_bridge_distance_m=nearest_dist,
    )

    return risk, markers, warnings


# ------------------------------------------------------
# Root (sanity check)
# ------------------------------------------------------

@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route",
    }


# ------------------------------------------------------
# Main API used by RouteSafe Navigator
# ------------------------------------------------------

@app.post("/api/route", response_model=RouteResponse)
def generate_route(req: RouteRequest):
    # 1) Geocode start/end
    start_lat, start_lon = geocode(req.start)
    end_lat, end_lon = geocode(req.end)

    # 2) Get main route from routing engine
    route = get_route(start_lat, start_lon, end_lat, end_lon)

    distance_km = route["distance"] / 1000.0
    duration_min = route["duration"] / 60.0

    coords: List[List[float]] = route["geometry"]["coordinates"]  # [lon, lat]

    # 3) Bridge analysis
    bridge_risk, bridge_markers, warnings = analyse_bridges(
        coords, req.vehicle_height_m
    )

    # 4) Turn-by-turn steps (human-readable instructions)
    steps: List[str] = []
    for leg in route.get("legs", []):
        for s in leg.get("steps", []):
            name = s.get("name", "")
            maneuver = s.get("maneuver", {})
            instr = maneuver.get("instruction") or maneuver.get("type", "Continue")
            if name:
                steps.append(f"{instr} – {name}")
            else:
                steps.append(instr)

    summary = RouteSummary(
        distance_km=distance_km,
        duration_min=duration_min,
    )

    response = RouteResponse(
        summary=summary,
        bridge_risk=bridge_risk,
        warnings=warnings,
        bridges=bridge_markers,
        steps=steps,
        main_geojson={
            "type": "LineString",
            "coordinates": coords,
        },
        alt_geojson=None,
    )

    return response