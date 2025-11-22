# backend/main.py
#
# FastAPI backend for RouteSafe – generates HGV legs, checks low bridges
# using our CSV, and returns a Google Maps URL with bridge pins per leg.

import os
from typing import List
from urllib.parse import urlencode, quote_plus

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from bridge_engine import BridgeEngine, BridgeCheckResult, Bridge

# --- Config -----------------------------------------------------------------

ORS_API_KEY = os.getenv("ORS_API_KEY")
if not ORS_API_KEY:
    raise RuntimeError("Please set ORS_API_KEY in your environment.")

ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-hgv"
ORS_GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"

# --- Models -----------------------------------------------------------------


class RouteRequest(BaseModel):
    # keys as they appear in JSON body from frontend
    vehicle_height_m: float = Field(..., alias="vehicleHeight")
    origin_postcode: str = Field(..., alias="originPostcode")
    delivery_postcodes: List[str] = Field(..., alias="deliveryPostcodes")


class RouteLeg(BaseModel):
    index: int
    start_postcode: str
    end_postcode: str
    distance_km: float
    duration_min: float
    vehicle_height_m: float
    has_conflict: bool
    near_height_limit: bool
    bridge_message: str
    safety_label: str
    google_maps_url: str
    bridge_points: List[dict]


class RouteResponse(BaseModel):
    legs: List[RouteLeg]


# --- App setup --------------------------------------------------------------


app = FastAPI(title="RouteSafe HGV Low-Bridge Checker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # frontend is separate (web/), so allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bridge_engine = BridgeEngine()


@app.get("/")
def root():
    """Simple root so hitting the backend URL doesn't show a 404."""
    return {"detail": "RouteSafe API is running. POST to /api/route."}


# --- Helpers ----------------------------------------------------------------


def geocode_postcode(postcode: str) -> (float, float):
    params = {
        "api_key": ORS_API_KEY,
        "text": postcode,
        "boundary.country": "GB",
        "size": 1,
    }
    r = requests.get(ORS_GEOCODE_URL, params=params, timeout=10)
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Geocoding failed for {postcode}: {r.text}",
        )

    data = r.json()
    features = data.get("features", [])
    if not features:
        raise HTTPException(
            status_code=404, detail=f"Postcode not found: {postcode}"
        )

    coords = features[0]["geometry"]["coordinates"]
    lon, lat = float(coords[0]), float(coords[1])
    return lat, lon


def fetch_leg_summary(
    start_lat: float, start_lon: float, end_lat: float, end_lon: float
) -> (float, float):
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    payload = {"coordinates": [[start_lon, start_lat], [end_lon, end_lat]]}

    r = requests.post(ORS_DIRECTIONS_URL, json=payload, headers=headers, timeout=15)
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Routing failed: {r.text}",
        )

    data = r.json()
    route = data["routes"][0]
    summary = route["summary"]
    distance_km = summary["distance"] / 1000.0
    duration_min = summary["duration"] / 60.0
    return distance_km, duration_min


def build_bridge_message(check: BridgeCheckResult) -> str:
    if check.has_conflict:
        return "⚠️ Low bridge on this leg. Route not HGV safe at current height."
    if check.near_height_limit:
        return "⚠️ Bridges close to your vehicle height – double-check before travelling."
    if check.nearest_bridge is None:
        return "No low bridges on this leg."
    return "No low bridges within the risk radius for this leg."


def build_safety_label(check: BridgeCheckResult) -> str:
    # Never show HGV SAFE if there is any conflict
    if check.has_conflict:
        return "LOW BRIDGE RISK"
    if check.near_height_limit:
        return "CHECK HEIGHT"
    return "HGV SAFE"


def build_google_maps_url(
    start_postcode: str,
    end_postcode: str,
    bridges: List[Bridge],
) -> str:
    """
    Build a Google Maps directions URL with bridge pins as waypoints.
    Pins come straight from our CSV via BridgeEngine.
    """
    origin = quote_plus(start_postcode)
    destination = quote_plus(end_postcode)

    params = {"api": "1", "origin": origin, "destination": destination}

    if bridges:
        waypoints = "|".join(f"{b.lat},{b.lon}" for b in bridges)
        params["waypoints"] = waypoints  # standard pins

    return "https://www.google.com/maps/dir/?" + urlencode(params, safe="|,")


# --- API route --------------------------------------------------------------


@app.post("/api/route", response_model=RouteResponse)
def generate_route(request: RouteRequest):
    """
    Generate route legs between origin and delivery postcodes,
    check them against low bridges and return leg summaries.
    """
    if not request.delivery_postcodes:
        raise HTTPException(
            status_code=400, detail="At least one delivery postcode is required"
        )

    stops = [request.origin_postcode] + request.delivery_postcodes
    legs: List[RouteLeg] = []

    for i in range(len(stops) - 1):
        start_pc = stops[i]
        end_pc = stops[i + 1]

        start_lat, start_lon = geocode_postcode(start_pc)
        end_lat, end_lon = geocode_postcode(end_pc)

        distance_km, duration_min = fetch_leg_summary(
            start_lat, start_lon, end_lat, end_lon
        )

        check = bridge_engine.check_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=request.vehicle_height_m,
        )

        bridge_list = check.conflict_bridges if check.conflict_bridges else check.near_bridges

        gm_url = build_google_maps_url(
            start_postcode=start_pc,
            end_postcode=end_pc,
            bridges=bridge_list,
        )

        leg = RouteLeg(
            index=i + 1,
            start_postcode=start_pc,
            end_postcode=end_pc,
            distance_km=round(distance_km, 1),
            duration_min=round(duration_min, 1),
            vehicle_height_m=request.vehicle_height_m,
            has_conflict=check.has_conflict,
            near_height_limit=check.near_height_limit,
            bridge_message=build_bridge_message(check),
            safety_label=build_safety_label(check),
            google_maps_url=gm_url,
            bridge_points=[
                {"lat": b.lat, "lon": b.lon, "height_m": b.height_m}
                for b in bridge_list
            ],
        )
        legs.append(leg)

    return RouteResponse(legs=legs)