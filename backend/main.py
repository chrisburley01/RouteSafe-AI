# ===========================
# RouteSafe-AI Backend (FULL)
# ===========================
#
# FastAPI service that:
#  - Normalises UK postcodes (LS270BN -> "LS27 0BN")
#  - Geocodes start/end via OpenRouteService
#  - Requests an HGV route from ORS
#  - Returns the raw ORS route payload + the cleaned postcodes
#
# Endpoint used by the front-end:
#   POST /api/route
#
# Root health check:
#   GET  /


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import os
import re


# ===========================
# CONFIG
# ===========================
# ORS API key from environment (Render → Environment)
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    # Fail fast if key is missing – helps debugging on Render
    raise RuntimeError("ORS_API_KEY environment variable is not set")


# ===========================
# FASTAPI APP
# ===========================
app = FastAPI(
    title="RouteSafe-AI",
    version="1.0",
    description="HGV low-bridge routing engine – avoid low bridges",
)

# CORS so the Navigator frontend (different domain) can call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can restrict to "https://routesafe-navigator.onrender.com"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================
# HELPERS
# ===========================
def normalise_uk_postcode(value: str) -> str:
    """
    Normalise UK postcodes like:
      "ls270bn"  -> "LS27 0BN"
      "M314qn"   -> "M31 4QN"
      "HD50RJ"   -> "HD5 0RJ"
    Only applies if the cleaned string length looks like a UK postcode (5–7 chars).
    """
    if not value:
        return value

    # Remove spaces and non-alphanumerics, force upper case
    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    # If it doesn't look like a UK postcode length, just return trimmed original
    if not (5 <= len(raw) <= 7):
        return value.strip()

    # Insert a space before the last 3 characters
    return f"{raw[:-3]} {raw[-3:]}"


def geocode_address(query: str):
    """
    Use OpenRouteService geocoding to turn a string into lon/lat.
    """
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
    # ORS returns [lon, lat]
    return coords[0], coords[1]


# ===========================
# REQUEST MODEL
# ===========================
class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ===========================
# ROUTE ENDPOINT
# ===========================
@app.post("/api/route")
def create_route(req: RouteRequest):
    """
    Main HGV routing endpoint.
    Called by RouteSafe Navigator front-end.
    """

    # 1) Normalise postcodes/addresses
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) Geocode both points
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) Request an HGV route from ORS
    directions_url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ]
        # later we can add 'extra_info', 'vehicle_type', etc.
    }
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post(directions_url, json=body, headers=headers, timeout=30)

    if r.status_code != 200:
        # Bubble the ORS error text for easier debugging
        raise HTTPException(
            status_code=400,
            detail=f"ORS routing failed: HTTP {r.status_code} – {r.text}",
        )

    route_data = r.json()

    # TODO: Plug in bridge_engine here to analyse each leg vs UK bridge dataset

    return {
        "ok": True,
        "start_used": start_query,
        "end_used": end_query,
        "route": route_data,
        # "bridge_risk": ... (future)
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