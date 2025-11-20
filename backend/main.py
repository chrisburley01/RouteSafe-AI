import os
import math
from typing import List, Optional, Dict, Any

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

ORS_API_KEY = os.getenv("ORS_API_KEY")
if not ORS_API_KEY:
    raise RuntimeError(
        "ORS_API_KEY environment variable is not set. "
        "Add it in Render → Environment."
    )

BRIDGE_CSV_PATH = os.path.join(os.path.dirname(__file__), "bridge_heights_clean.csv")

ORS_GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-hgv"


# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approx distance in metres between two lat/lon points."""
    R = 6371000.0  # metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# -------------------------------------------------------------------
# Bridge engine
# -------------------------------------------------------------------

class BridgeRecord(BaseModel):
    name: Optional[str]
    lat: float
    lon: float
    height_m: float


class BridgeEngine:
    def __init__(self, csv_path: str):
        if not os.path.exists(csv_path):
            raise RuntimeError(f"Bridge CSV not found at {csv_path}")

        df = pd.read_csv(csv_path)

        cols_lower = {c.lower(): c for c in df.columns}

        # Try to detect lat / lon / height columns flexibly
        def find_col(candidates):
            for cand in candidates:
                if cand in cols_lower:
                    return cols_lower[cand]
            for c in df.columns:
                cl = c.lower()
                if any(cl.startswith(p) for p in candidates):
                    return c
            return None

        lat_col = find_col(["lat", "latitude"])
        lon_col = find_col(["lon", "lng", "longitude"])
        height_col = find_col(["height_m", "height (m)", "heightm", "height"])

        if not (lat_col and lon_col and height_col):
            raise RuntimeError(
                f"Bridge CSV is missing required columns. "
                f"Found columns: {list(df.columns)}"
            )

        name_col = find_col(["name", "bridge", "structure"])

        records: List[BridgeRecord] = []
        for _, row in df.iterrows():
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
                h = float(row[height_col])
            except Exception:
                continue

            name = str(row[name_col]) if name_col and not pd.isna(row[name_col]) else None
            records.append(BridgeRecord(name=name, lat=lat, lon=lon, height_m=h))

        if not records:
            raise RuntimeError("No valid bridge records loaded from CSV.")

        self.bridges = records

    def find_low_bridges_between_points(
        self,
        a_lat: float,
        a_lon: float,
        b_lat: float,
        b_lon: float,
        vehicle_height_m: float,
        height_margin_m: float = 0.0,
        corridor_km: float = 2.0,
    ) -> List[Dict[str, Any]]:
        """
        Very simple heuristic: take a bounding box around the two points,
        padded by `corridor_km`, and return any bridges within that box
        whose height is less than vehicle_height_m + margin.
        """
        min_lat = min(a_lat, b_lat)
        max_lat = max(a_lat, b_lat)
        min_lon = min(a_lon, b_lon)
        max_lon = max(a_lon, b_lon)

        # Roughly convert corridor_km to ~degrees (works fine for UK scale)
        lat_pad = corridor_km / 111.0
        lon_pad = corridor_km / 70.0  # UK-ish

        min_lat -= lat_pad
        max_lat += lat_pad
        min_lon -= lon_pad
        max_lon += lon_pad

        threshold = vehicle_height_m + height_margin_m

        results: List[Dict[str, Any]] = []
        for br in self.bridges:
            if not (min_lat <= br.lat <= max_lat and min_lon <= br.lon <= max_lon):
                continue

            if br.height_m < threshold:
                # Approx distance from start, just for info
                dist_from_start_m = haversine_m(a_lat, a_lon, br.lat, br.lon)
                results.append(
                    {
                        "name": br.name,
                        "lat": br.lat,
                        "lon": br.lon,
                        "bridge_height_m": br.height_m,
                        "vehicle_height_m": vehicle_height_m,
                        "distance_from_start_m": round(dist_from_start_m, 1),
                    }
                )

        # Sort nearest first
        results.sort(key=lambda r: r["distance_from_start_m"])
        return results


bridge_engine = BridgeEngine(BRIDGE_CSV_PATH)


# -------------------------------------------------------------------
# ORS helpers
# -------------------------------------------------------------------

def geocode_postcode(postcode: str) -> Dict[str, float]:
    """Use ORS geocoding to convert postcode → lat/lon."""
    params = {
        "api_key": ORS_API_KEY,
        "text": postcode,
        "boundary.country": "GBR",
        "size": 1,
    }
    resp = requests.get(ORS_GEOCODE_URL, params=params, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Geocoding failed for '{postcode}' (status {resp.status_code})",
        )

    data = resp.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(
            status_code=404,
            detail=f"Could not geocode postcode '{postcode}'.",
        )

    coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
    lon, lat = float(coords[0]), float(coords[1])
    return {"lat": lat, "lon": lon}


def get_hgv_route_metrics(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
) -> Dict[str, float]:
    """
    Call ORS driving-hgv directions and return total distance (km) and duration (minutes).
    """
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ]
    }
    resp = requests.post(ORS_DIRECTIONS_URL, json=body, headers=headers, timeout=25)

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Routing failed (status {resp.status_code}): {resp.text[:200]}",
        )

    data = resp.json()
    try:
        summary = data["features"][0]["properties"]["summary"]
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail="Unexpected routing response.")

    distance_km = summary["distance"] / 1000.0
    duration_min = summary["duration"] / 60.0

    return {
        "distance_km": round(distance_km, 2),
        "duration_min": round(duration_min, 1),
    }


# -------------------------------------------------------------------
# FastAPI app + CORS
# -------------------------------------------------------------------

app = FastAPI(
    title="RouteSafe AI",
    description="Prototype – check HGV routes against low bridges",
    version="0.1.0",
)

# Allow frontend (GitHub Pages etc.) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can tighten this later to your exact frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------

class RouteRequest(BaseModel):
    depot_postcode: str = Field(..., description="Starting postcode (depot)")
    stops: List[str] = Field(..., description="List of delivery postcodes in order")
    vehicle_height_m: float = Field(..., gt=0, description="Vehicle height in metres")


class BridgeWarning(BaseModel):
    name: Optional[str]
    lat: float
    lon: float
    bridge_height_m: float
    vehicle_height_m: float
    distance_from_start_m: float


class LegResult(BaseModel):
    from_postcode: str
    to_postcode: str
    distance_km: float
    duration_min: float
    vehicle_height_m: float
    low_bridges: List[BridgeWarning]


class RouteResponse(BaseModel):
    legs: List[LegResult]


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok", "bridges_loaded": len(bridge_engine.bridges)}


@app.post("/api/route", response_model=RouteResponse)
def calculate_route(req: RouteRequest):
    """
    Calculate HGV route legs between depot and each stop, check each leg
    for possible low bridges, and return summary per leg.
    """

    if not req.stops:
        raise HTTPException(status_code=422, detail="At least one delivery stop is required.")

    # Step 1 – geocode all postcodes
    all_postcodes = [req.depot_postcode] + req.stops
    coords: Dict[str, Dict[str, float]] = {}
    for pc in all_postcodes:
        coords[pc] = geocode_postcode(pc)

    # Step 2 – build legs (Depot -> stop1, stop1 -> stop2, ...)
    legs: List[LegResult] = []
    chain = all_postcodes
    for i in range(len(chain) - 1):
        from_pc = chain[i]
        to_pc = chain[i + 1]

        start = coords[from_pc]
        end = coords[to_pc]

        # ORS route metrics
        metrics = get_hgv_route_metrics(
            start_lon=start["lon"],
            start_lat=start["lat"],
            end_lon=end["lon"],
            end_lat=end["lat"],
        )

        # Bridge checks – simple bounding-box heuristic
        bridge_dicts = bridge_engine.find_low_bridges_between_points(
            a_lat=start["lat"],
            a_lon=start["lon"],
            b_lat=end["lat"],
            b_lon=end["lon"],
            vehicle_height_m=req.vehicle_height_m,
            height_margin_m=0.0,
            corridor_km=2.0,
        )

        warnings = [BridgeWarning(**b) for b in bridge_dicts]

        leg = LegResult(
            from_postcode=from_pc.upper(),
            to_postcode=to_pc.upper(),
            distance_km=metrics["distance_km"],
            duration_min=metrics["duration_min"],
            vehicle_height_m=req.vehicle_height_m,
            low_bridges=warnings,
        )
        legs.append(leg)

    return RouteResponse(legs=legs)
