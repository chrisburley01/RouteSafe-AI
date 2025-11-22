
# ===========================
# RouteSafe-AI Backend (FULL)
# ===========================
#
# - Normalises UK postcodes
# - Geocodes start/end via OpenRouteService
# - Requests an HGV route from ORS
# - Checks the straight-line leg vs UK low-bridge data
# - Returns route + bridge risk summary for RouteSafe Navigator
#

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import os
import re
import math
import requests
import pandas as pd
from dataclasses import dataclass
from typing import Optional, List


# ===========================
# CONFIG
# ===========================

ORS_API_KEY = os.getenv("ORS_API_KEY")
if not ORS_API_KEY:
    raise RuntimeError("ORS_API_KEY environment variable is not set")

BRIDGE_CSV_PATH = "bridge_heights_clean.csv"  # must sit next to main.py
EARTH_RADIUS_M = 6_371_000.0


# ===========================
# FASTAPI APP + CORS
# ===========================

app = FastAPI(
    title="RouteSafe-AI",
    version="1.1",
    description="HGV low-bridge routing engine – avoid low bridges",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can lock this down later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================
# UK POSTCODE NORMALISER
# ===========================

def normalise_uk_postcode(value: str) -> str:
    """
    Normalise UK postcodes like:
      'ls270bn' -> 'LS27 0BN'
      'M314qn'  -> 'M31 4QN'
    Only kicks in if the cleaned token length looks like a UK postcode.
    """
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    if not (5 <= len(raw) <= 7):
        return value.strip()

    return f"{raw[:-3]} {raw[-3:]}"


# ===========================
# BRIDGE ENGINE
# ===========================

@dataclass
class Bridge:
    lat: float
    lon: float
    height_m: float


@dataclass
class BridgeCheckResult:
    has_conflict: bool
    near_height_limit: bool
    nearest_bridge: Optional[Bridge]
    nearest_distance_m: Optional[float]


def _latlon_to_xy(lat: float, lon: float, ref_lat: float) -> (float, float):
    """
    Approximate conversion from lat/lon to metres in a local tangent plane.
    Good enough for ~few km around the leg.
    """
    x = math.radians(lon) * EARTH_RADIUS_M * math.cos(math.radians(ref_lat))
    y = math.radians(lat) * EARTH_RADIUS_M
    return x, y


def _point_to_segment_distance(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    """
    Euclidean distance from (px, py) to the line segment (x1, y1) – (x2, y2).
    """
    dx = x2 - x1
    dy = y2 - y1

    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)

    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


class BridgeEngine:
    """
    Simple bridge engine:
      - loads bridge_heights_clean.csv (lat, lon, height_m)
      - checks a leg (start → end) for nearby bridges
    """

    def __init__(
        self,
        csv_path: str,
        search_radius_m: float = 300.0,
        conflict_clearance_m: float = 0.0,
        near_clearance_m: float = 0.25,
    ):
        self.search_radius_m = search_radius_m
        self.conflict_clearance_m = conflict_clearance_m
        self.near_clearance_m = near_clearance_m

        df = pd.read_csv(csv_path)
        self.bridges: List[Bridge] = [
            Bridge(float(row["lat"]), float(row["lon"]), float(row["height_m"]))
            for _, row in df.iterrows()
        ]

    def check_leg(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        vehicle_height_m: float,
    ) -> BridgeCheckResult:
        ref_lat = (start_lat + end_lat) / 2.0

        sx, sy = _latlon_to_xy(start_lat, start_lon, ref_lat)
        ex, ey = _latlon_to_xy(end_lat, end_lon, ref_lat)

        nearest_bridge: Optional[Bridge] = None
        nearest_distance_m: Optional[float] = None
        has_conflict = False
        near_height_limit = False

        for b in self.bridges:
            bx, by = _latlon_to_xy(b.lat, b.lon, ref_lat)
            d = _point_to_segment_distance(bx, by, sx, sy, ex, ey)

            if d > self.search_radius_m:
                continue

            # Clearance below bridge
            clearance = b.height_m - vehicle_height_m

            if clearance < self.conflict_clearance_m:
                has_conflict = True
            elif clearance < self.near_clearance_m:
                near_height_limit = True

            if nearest_bridge is None or d < nearest_distance_m:
                nearest_bridge = b
                nearest_distance_m = d

        return BridgeCheckResult(
            has_conflict=has_conflict,
            near_height_limit=near_height_limit,
            nearest_bridge=nearest_bridge,
            nearest_distance_m=nearest_distance_m,
        )


bridge_engine = BridgeEngine(
    csv_path=BRIDGE_CSV_PATH,
    search_radius_m=300.0,        # how far from leg to look (metres)
    conflict_clearance_m=0.0,     # ≤ 0m = definite conflict
    near_clearance_m=0.25,        # within 25cm = "near limit"
)


# ===========================
# REQUEST MODEL
# ===========================

class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True  # reserved for future route re-planning


# ===========================
# GEOCODING
# ===========================

def geocode_address(query: str):
    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query}

    r = requests.get(url, params=params, timeout=15)
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS geocode failed for '{query}': HTTP {r.status_code}",
        )

    data = r.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {query}")

    coords = features[0]["geometry"]["coordinates"]
    return coords[0], coords[1]  # lon, lat


# ===========================
# MAIN ROUTE ENDPOINT
# ===========================

@app.post("/api/route")
def create_route(req: RouteRequest):
    # 1) Clean up postcodes / addresses
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) Geocode
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) Ask ORS for an HGV route
    directions_url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ],
    }
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post(directions_url, json=body, headers=headers, timeout=30)
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS routing failed: HTTP {r.status_code} – {r.text}",
        )

    route_data = r.json()

    # Extract distance / duration if present
    distance_m = None
    duration_s = None
    try:
        first_route = (route_data.get("routes") or [])[0]
        summary = first_route.get("summary") or {}
        distance_m = summary.get("distance")
        duration_s = summary.get("duration")
    except Exception:
        pass

    # 4) Run the bridge engine on the leg
    bridge_result = bridge_engine.check_leg(
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
        vehicle_height_m=req.vehicle_height_m,
    )

    # Map bridge result to a simple risk label + message
    if bridge_result.has_conflict:
        risk_level = "high"
        risk_message = "Route intersects a low bridge below vehicle height"
    elif bridge_result.near_height_limit:
        risk_level = "medium"
        risk_message = "Route passes near a bridge close to height limit"
    else:
        risk_level = "low"
        risk_message = "No low-bridge conflicts detected"

    nearest_bridge_info = None
    if bridge_result.nearest_bridge is not None:
        nearest_bridge_info = {
            "lat": bridge_result.nearest_bridge.lat,
            "lon": bridge_result.nearest_bridge.lon,
            "height_m": bridge_result.nearest_bridge.height_m,
            "distance_m": bridge_result.nearest_distance_m,
        }

    return {
        "ok": True,
        "start_used": start_query,
        "end_used": end_query,
        "route": route_data,
        "route_summary": {
            "distance_m": distance_m,
            "duration_s": duration_s,
        },
        "bridge_summary": {
            "has_conflict": bridge_result.has_conflict,
            "near_height_limit": bridge_result.near_height_limit,
            "risk_level": risk_level,
            "risk_message": risk_message,
            "nearest_bridge": nearest_bridge_info,
        },
    }


# ===========================
# ROOT HEALTH CHECK
# ===========================

@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route",
    }