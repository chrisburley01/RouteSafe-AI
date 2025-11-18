# main.py

import math
from typing import List, Tuple

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bridge_engine import BridgeEngine

# -------- CONFIG -------- #

USER_AGENT = "RouteSafeAI/0.1 (contact: example@example.com)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"

app = FastAPI(title="RouteSafe AI", version="0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chrisburley01.github.io",
        "https://chrisburley01.github.io/RouteSafe-AI",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global bridge engine instance
bridge_engine = BridgeEngine(
    csv_path="bridge_heights_clean.csv",
    search_radius_m=300.0,
    conflict_clearance_m=0.0,
    near_clearance_m=0.25,
)


# -------- MODELS -------- #

class RouteRequest(BaseModel):
    depot_postcode: str
    delivery_postcodes: List[str]
    vehicle_height_m: float


class Leg(BaseModel):
    from_: str
    to: str
    distance_km: float
    duration_min: float
    near_height_limit: bool = False


class RouteResponse(BaseModel):
    total_distance_km: float
    total_duration_min: float
    legs: List[Leg]


# -------- UTILS -------- #

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    params = {
        "q": postcode,
        "format": "json",
        "limit": 1,
        "countrycodes": "gb",
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(
            f"{NOMINATIM_URL}/search", params=params, headers=headers, timeout=10
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Geocoding error: {e}")

    data = resp.json()
    if not data:
        raise HTTPException(status_code=404, detail=f"Could not geocode postcode: {postcode}")

    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return lat, lon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def estimate_leg(
    from_pc: str, to_pc: str
) -> Tuple[float, float, float, float]:
    """
    TEMP: straight-line distance * 1.3 to approximate road distance.
    Returns distance_km, duration_min, start_lat, start_lon, end_lat, end_lon
    """
    lat1, lon1 = geocode_postcode(from_pc)
    lat2, lon2 = geocode_postcode(to_pc)

    crow_km = haversine_km(lat1, lon1, lat2, lon2)
    road_km = crow_km * 1.3
    duration_hours = road_km / 60.0
    duration_min = duration_hours * 60

    return road_km, duration_min, lat1, lon1, lat2, lon2


# -------- ROUTES -------- #

@app.get("/")
def root():
    return {"status": "ok", "service": "RouteSafe AI", "version": "0.2"}


@app.post("/route", response_model=RouteResponse)
def route_endpoint(request: RouteRequest):
    depot = request.depot_postcode.strip().upper()
    deliveries = [pc.strip().upper() for pc in request.delivery_postcodes if pc.strip()]

    if not depot:
        raise HTTPException(status_code=400, detail="Depot postcode is required.")
    if not deliveries:
        raise HTTPException(status_code=400, detail="At least one delivery postcode is required.")

    all_points = [depot] + deliveries
    legs: List[Leg] = []
    total_distance = 0.0
    total_duration = 0.0

    for i in range(len(all_points) - 1):
        from_pc = all_points[i]
        to_pc = all_points[i + 1]

        distance_km, duration_min, lat1, lon1, lat2, lon2 = estimate_leg(from_pc, to_pc)

        # Bridge check
        bridge_result = bridge_engine.check_leg(
            start_lat=lat1,
            start_lon=lon1,
            end_lat=lat2,
            end_lon=lon2,
            vehicle_height_m=request.vehicle_height_m,
        )

        leg = Leg(
            from_=from_pc,
            to=to_pc,
            distance_km=distance_km,
            duration_min=duration_min,
            near_height_limit=bridge_result.near_height_limit,
        )
        legs.append(leg)
        total_distance += distance_km
        total_duration += duration_min

    return RouteResponse(
        total_distance_km=total_distance,
        total_duration_min=total_duration,
        legs=legs,
    )


# Simple stub so the /ocr call doesn't crash (photo reading can come later)
@app.post("/ocr")
async def ocr_stub(file: UploadFile = File(...)):
    content = await file.read()
    # Not doing real OCR yet – just return empty list
    return {"raw_text": "", "postcodes": []}