# ===========================
# RouteSafe-AI Backend (FULL, v1.1 with CORS)
# ===========================
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import os
import re

# ORS API key
ORS_API_KEY = os.getenv("ORS_API_KEY")

app = FastAPI(
    title="RouteSafe-AI",
    version="1.1",
    description="HGV low-bridge routing engine – avoid low bridges",
)

# ------------------------------------------------------------
# CORS – allow the Navigator frontend to call this API
# ------------------------------------------------------------
# You can tighten this list if you want, but this will
# definitely allow both your Render frontend + any dev hosts.
ALLOWED_ORIGINS = [
    "https://routesafe-navigator.onrender.com",
    "https://routesafe-navigator.onrender.com/",
    "https://chrisburley01.github.io",
    "https://chrisburley01.github.io/",
    "http://localhost",
    "http://localhost:5173",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# UK POSTCODE NORMALISER (fix for LS270BN, M314QN, HD50RJ etc.)
# ------------------------------------------------------------
def normalise_uk_postcode(value: str) -> str:
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    # Only normalise values that look like UK postcodes
    if 5 <= len(raw) <= 7:
        return f"{raw[:-3]} {raw[-3:]}"
    # Fallback: just trimmed original string
    return value.strip()


# ------------------------------------------------------------
# Request model
# ------------------------------------------------------------
class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ------------------------------------------------------------
# Geocoding using ORS
# ------------------------------------------------------------
def geocode_address(query: str):
    if not ORS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ORS_API_KEY is not configured on the server.",
        )

    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query}

    r = requests.get(url, params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"ORS geocode failed: {query}")

    data = r.json()
    if not data.get("features"):
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {query}")

    coords = data["features"][0]["geometry"]["coordinates"]
    return coords[0], coords[1]  # lon, lat


# ------------------------------------------------------------
# Route engine (ORS directions + your bridge engine later)
# ------------------------------------------------------------
@app.post("/api/route")
def create_route(req: RouteRequest):
    # 1) CLEAN THE POSTCODES FIRST
    start_query = normalise_uk_postcode(req.start)
    end_query = normalise_uk_postcode(req.end)

    # 2) GEOCODE
    start_lon, start_lat = geocode_address(start_query)
    end_lon, end_lat = geocode_address(end_query)

    # 3) ORS routing (HGV profile)
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat],
        ]
    }
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}

    r = requests.post(url, json=body, headers=headers)

    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"ORS routing failed: {r.text}")

    route = r.json()

    # Bridge-engine hook will go here later

    return {
        "ok": True,
        "start_used": start_query,
        "end_used": end_query,
        "route": route,
    }


# ------------------------------------------------------------
# Base endpoint
# ------------------------------------------------------------
@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route",
    }