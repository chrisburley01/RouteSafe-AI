# backend/main.py

import os
import math
import re
from io import BytesIO
from typing import List, Tuple

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from PIL import Image
import pytesseract

app = FastAPI(title="RouteSafe AI Backend", version="0.1")

# ---------- MODELS ---------- #


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


class OCRResult(BaseModel):
    raw_text: str
    postcodes: List[str]


# ---------- CONFIG ---------- #

USER_AGENT = "RouteSafeAI/0.1 (contact: your-email@example.com)"


# ---------- UTIL: OCR & POSTCODES ---------- #

UK_POSTCODE_REGEX = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.IGNORECASE
)


def extract_text_from_image(image_bytes: bytes) -> str:
    """
    Run OCR on the image bytes using Tesseract.
    """
    try:
        image = Image.open(BytesIO(image_bytes))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    # Optional preprocessing could be added here (grayscale, threshold, etc.)
    text = pytesseract.image_to_string(image)
    return text


def extract_postcodes_from_text(text: str) -> List[str]:
    """
    Extract UK-style postcodes in the order they appear.
    Deduplicate while preserving order.
    """
    matches = UK_POSTCODE_REGEX.findall(text.upper())
    seen = set()
    ordered = []
    for m in matches:
        pc = " ".join(m.split())  # normalise spaces
        if pc not in seen:
            seen.add(pc)
            ordered.append(pc)
    return ordered


# ---------- UTIL: GEO & DISTANCE ---------- #


def geocode_postcode(postcode: str) -> Tuple[float, float]:
    """
    Geocode a postcode to lat/lon using OpenStreetMap Nominatim.

    This is fine for a prototype but has usage limits.
    For production you'll want a dedicated geocoding service.
    """
    params = {
        "q": postcode,
        "format": "json",
        "limit": 1,
        "countrycodes": "gb",
    }
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=headers,
            timeout=10,
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
    """
    Great-circle distance in km between two points.
    """
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


def estimate_drive_distance_and_time(
    from_pc: str, to_pc: str
) -> Tuple[float, float]:
    """
    Prototype: estimate road distance/time using straight line * factor.
    In production, replace this with a call to a proper routing API
    (GraphHopper, TomTom, HERE, etc.) that:
      - Uses a TRUCK profile
      - Respects maxheight & other HGV restrictions.

    Returns (distance_km, duration_min).
    """
    lat1, lon1 = geocode_postcode(from_pc)
    lat2, lon2 = geocode_postcode(to_pc)
    crow_km = haversine_km(lat1, lon1, lat2, lon2)

    # Very rough "road distance" conversion factor
    road_km = crow_km * 1.3

    # Assume 60 km/h average incl. stops
    duration_hours = road_km / 60.0
    duration_min = duration_hours * 60

    return road_km, duration_min


def get_hgv_leg(
    from_pc: str,
    to_pc: str,
    vehicle_height_m: float,
) -> Leg:
    """
    Wrapper to plan a leg between two postcodes for a given vehicle height.

    TODO for production:
      - Replace 'estimate_drive_distance_and_time' with a call to your
        chosen HGV routing API, passing the vehicle height so it avoids
        low bridges for that specific trailer height.

    For now:
      - Uses naive distance estimate and NO real bridge logic.
    """
    distance_km, duration_min = estimate_drive_distance_and_time(from_pc, to_pc)

    # Stub: no real height restriction logic yet
    near_height_limit = False

    return Leg(
        from_=from_pc,
        to=to_pc,
        distance_km=distance_km,
        duration_min=duration_min,
        near_height_limit=near_height_limit,
    )


# ---------- ENDPOINTS ---------- #


@app.get("/")
def root():
    return {"status": "ok", "service": "RouteSafe AI", "version": "0.1"}


@app.post("/ocr", response_model=OCRResult)
async def ocr_endpoint(file: UploadFile = File(...)):
    """
    Accept an image (photo of a plan), OCR it, and extract UK postcodes in order.
    """
    if file.content_type is None or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    text = extract_text_from_image(image_bytes)
    postcodes = extract_postcodes_from_text(text)

    if not postcodes:
        # Still return text so you can debug
        raise HTTPException(
            status_code=422,
            detail="No UK postcodes found in the image. Check clarity/angle.",
        )

    return OCRResult(raw_text=text, postcodes=postcodes)


@app.post("/route", response_model=RouteResponse)
def route_endpoint(request: RouteRequest):
    """
    Accept depot + ordered delivery postcodes + vehicle height, and
    return legs in the SAME order, with estimated distance/time.

    For now, this does not yet truly avoid low bridges.
    A dev needs to plug in a proper HGV routing API inside get_hgv_leg().
    """
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

        leg = get_hgv_leg(from_pc, to_pc, request.vehicle_height_m)
        legs.append(leg)
        total_distance += leg.distance_km
        total_duration += leg.duration_min

    return RouteResponse(
        total_distance_km=total_distance,
        total_duration_min=total_duration,
        legs=legs,
    )