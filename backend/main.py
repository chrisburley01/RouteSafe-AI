import os
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bridge_engine import BridgeEngine
import requests
import json

# ---------------------------------------------------
# FASTAPI SETUP
# ---------------------------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------
# LOAD ENV VARS
# ---------------------------------------------------
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    raise RuntimeError("ORS_API_KEY is missing in Render environment variables.")

# ---------------------------------------------------
# LOAD BRIDGE ENGINE
# ---------------------------------------------------
bridge_engine = BridgeEngine("bridge_heights_clean.csv")

# ---------------------------------------------------
# REQUEST MODEL FOR /api/route
# ---------------------------------------------------
class RouteRequest(BaseModel):
    depot_postcode: str
    stops: list[str]
    vehicle_height_m: float

# ---------------------------------------------------
# UTILITY — geocode postcode using ORS
# ---------------------------------------------------
def geocode_postcode(postcode: str):
    url = f"https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": postcode,
        "size": 1,
        "boundary.country": "GB"
    }
    r = requests.get(url, params=params)

    if r.status_code != 200:
        raise RuntimeError(f"ORS geocoding error: {r.text}")

    data = r.json()
    if not data["features"]:
        raise RuntimeError(f"Postcode not found: {postcode}")

    lon, lat = data["features"][0]["geometry"]["coordinates"]
    return lat, lon

# ---------------------------------------------------
# ROUTING USING ORS
# ---------------------------------------------------
def get_route(lat1, lon1, lat2, lon2):
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
    payload = {
        "coordinates": [
            [lon1, lat1],
            [lon2, lat2]
        ],
        "profile": "driving-hgv",
        "extra_info": ["height"],
    }

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }

    r = requests.post(url, headers=headers, data=json.dumps(payload))

    if r.status_code != 200:
        raise RuntimeError(f"ORS routing error: {r.text}")

    return r.json()

# ---------------------------------------------------
# 📌 MAIN ENDPOINT — /api/route
# ---------------------------------------------------
@app.post("/api/route")
def generate_safe_route(req: RouteRequest):
    depot_lat, depot_lon = geocode_postcode(req.depot_postcode)

    results = []
    last_lat, last_lon = depot_lat, depot_lon

    for stop in req.stops:
        stop_lat, stop_lon = geocode_postcode(stop)

        route_data = get_route(last_lat, last_lon, stop_lat, stop_lon)

        # Check for bridges along the path
        bridge_hits = bridge_engine.check_route_for_bridges(
            last_lat, last_lon, stop_lat, stop_lon, req.vehicle_height_m
        )

        results.append({
            "from": req.depot_postcode,
            "to": stop,
            "route_data": route_data,
            "bridge_hits": bridge_hits
        })

        last_lat, last_lon = stop_lat, stop_lon

    return {"legs": results}

# ---------------------------------------------------
# 📌 OCR ENDPOINT — /api/ocr  (kept separate)
# ---------------------------------------------------
@app.post("/api/ocr")
async def ocr_image(file: UploadFile = File(...)):
    data = await file.read()
    # Dummy return — your OCR model would go here
    return {"filename": file.filename, "text": "OCR placeholder"}

# ---------------------------------------------------
# ROOT TEST
# ---------------------------------------------------
@app.get("/")
def home():
    return {"status": "OK", "message": "RouteSafe AI backend running."}
