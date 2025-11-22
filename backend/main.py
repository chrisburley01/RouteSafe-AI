# ===========================
# RouteSafe-AI Backend (FULL)
# ===========================
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os
import re

# ORS API key
ORS_API_KEY = os.getenv("ORS_API_KEY")

app = FastAPI(
    title="RouteSafe-AI",
    version="1.0",
    description="HGV low-bridge routing engine – avoid low bridges"
)


# ------------------------------------------------------------
# UK POSTCODE NORMALISER (fix for LS270BN, M314QN, HD50RJ etc.)
# ------------------------------------------------------------
def normalise_uk_postcode(value: str) -> str:
    if not value:
        return value

    raw = re.sub(r"[^A-Za-z0-9]", "", value).upper()

    # Only normalise values that look like UK postcodes
    if not (5 <= len(raw) <= 7):
        return value.strip()

    return f"{raw[:-3]} {raw[-3:]}"


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
    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": query}

    r = requests.get(url, params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"ORS geocode failed: {query}")

    data = r.json()
    if not data.get("features"):
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {query}")

    coords = data["features"][0]["geometry"]["coordinates"]
    return coords[0], coords[1]   # lon, lat


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
            [end_lon, end_lat]
        ]
    }
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}

    r = requests.post(url, json=body, headers=headers)

    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"ORS routing failed: {r.text}")

    route = r.json()

    # You can plug the bridge-engine in here

    return {
        "ok": True,
        "start_used": start_query,
        "end_used": end_query,
        "route": route
    }


# ------------------------------------------------------------
# Base endpoint
# ------------------------------------------------------------
@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine – use POST /api/route"
    }