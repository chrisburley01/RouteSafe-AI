# ===============================
# RouteSafe-AI backend  (v5.0R-no-polyline)
# HGV low-bridge routing engine
# ===============================

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Tuple
import os
import re
import requests

from bridge_engine import BridgeEngine, BridgeCheckResult

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    # Fail fast if key not set – easier to debug on Render
    raise RuntimeError("ORS_API_KEY environment variable is not set")

app = FastAPI(
    title="RouteSafe-AI",
    version="5.0R",
    description="HGV low-bridge routing engine – ORS + UK bridge data",
)

# Single bridge engine instance (loads CSV once at startup)
bridge_engine = BridgeEngine(csv_path="bridge_heights_clean.csv")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def normalise_uk_postcode(value: str) -> str:
    """
    Normalise UK postcodes:
    LS270BN -> LS27 0BN
    m314qn  -> M31 4QN
    """
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    # Only normalise values that *look* like postcodes
    if not (5 <= len(raw) <= 7):
        return value.strip()

    return f"{raw[:-3]} {raw[-3:]}"


def geocode_address(query: str) -> Tuple[float, float]:
    """
    Geocode with ORS. Returns (lon, lat).
    """
    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query}

    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS geocode failed for '{query}': {r.text}",
        )

    data = r.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(
            status_code=400, detail=f"Unable to geocode: {query}"
        )

    coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
    return coords[0], coords[1]


def decode_ors_polyline(encoded: str, precision: int = 5) -> List[Tuple[float, float]]:
    """
    Decode an encoded polyline (Google polyline algorithm) into
    a list of (lat, lon) pairs. ORS uses this format by default.
    """
    if not encoded:
        return []

    coordinates: List[Tuple[float, float]] = []
    index = 0
    lat = 0
    lng = 0
    factor = 10 ** precision

    length = len(encoded)

    while index < length:
        # Decode latitude
        result = 0
        shift = 0
        while True:
            if index >= length:
                break
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        # Decode longitude
        result = 0
        shift = 0
        while True:
            if index >= length:
                break
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        coordinates.append((lat / factor, lng / factor))

    return coordinates


# ------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------
class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ------------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------------
@app.post("/api/route")
def create_route(req: RouteRequest):
    """
    Main routing endpoint used by RouteSafe Navigator.
    1) Clean & geocode postcodes
    2) Fetch HGV route from ORS
    3) Decode geometry -> list of coordinates
    4) Run low-bridge risk check across the route
    5) Return summary + warnings + route coordinates
    """

    # --- 1. Clean postcodes ----------------------------------------
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # --- 2. Geocode ------------------------------------------------
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # --- 3. ORS routing (no geometry_format param – that caused 400) ----
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ]
        # Keep payload simple & compatible with current ORS
    }
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post(url, json=body, headers=headers, timeout=40)
    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"ORS routing failed (400): {r.text}",
        )

    data = r.json()
    routes = data.get("routes") or []
    if not routes:
        raise HTTPException(
            status_code=400,
            detail="No route returned from ORS.",
        )

    route0 = routes[0]
    summary = route0.get("summary", {})
    distance_m = float(summary.get("distance", 0.0))
    duration_s = float(summary.get("duration", 0.0))

    # ORS default is encoded polyline string
    encoded_geom = route0.get("geometry")
    if not encoded_geom:
        raise HTTPException(
            status_code=400,
            detail="ORS response missing geometry.",
        )

    # Decode to [(lat, lon), ...]
    coords_latlon: List[Tuple[float, float]] = decode_ors_polyline(encoded_geom)

    # For bridge engine we want [lon, lat]
    coords_lonlat: List[Tuple[float, float]] = [
        (lon, lat) for (lat, lon) in coords_latlon
    ]

    # --- 4. Bridge risk analysis -----------------------------------
    bridge_result: BridgeCheckResult = bridge_engine.check_route(
        coords_lonlat, req.vehicle_height_m
    )

    # Risk label for UI
    if bridge_result.has_conflict:
        risk_label = "high"
    elif bridge_result.near_height_limit:
        risk_label = "medium"
    else:
        risk_label = "low"

    nearest_height = (
        bridge_result.nearest_bridge.height_m
        if bridge_result.nearest_bridge
        else None
    )
    nearest_distance = bridge_result.nearest_distance_m

    # Build warnings list for UI
    warnings_payload = []
    for w in bridge_result.warnings:
        warnings_payload.append(
            {
                "lat": w.bridge.lat,
                "lon": w.bridge.lon,
                "bridge_height_m": w.bridge.height_m,
                "distance_m": w.distance_m,
                "severity": w.severity,
                "message": w.message,
            }
        )

    # --- 5. Response payload (v5-style) -----------------------------
    return {
        "ok": True,
        "engine": "RouteSafe-AI v5.0R",
        "start_used": start_query,
        "end_used": end_query,
        "summary": {
            "distance_km": round(distance_m / 1000.0, 2),
            "duration_minutes": int(round(duration_s / 60.0)),
            "bridge_risk": risk_label,
            "nearest_bridge_height_m": nearest_height,
            "nearest_bridge_distance_m": (
                round(nearest_distance, 1) if nearest_distance else None
            ),
        },
        "route": {
            # For Leaflet: [lat, lon] pairs
            "coordinates": [[lat, lon] for (lat, lon) in coords_latlon],
        },
        "warnings": warnings_payload,
    }


@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "version": "5.0R-no-polyline",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route",
    }