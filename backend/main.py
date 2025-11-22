from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import math
import os

# ------------------------------
# CONFIG
# ------------------------------

ORS_API_KEY = "5b3ce3597851110001cf62480d8bd4326e784b2995c1a56e31f99909"  # Your real ORS key
ORS_URL = "https://api.openrouteservice.org/v2/directions/driving-hgv"

BRIDGE_CSV = "bridge_heights_clean.csv"

# Load bridge data
import pandas as pd
bridges_df = pd.read_csv(BRIDGE_CSV)


# ------------------------------
# FASTAPI SETUP
# ------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------
# REQUEST MODEL
# ------------------------------
class RouteRequest(BaseModel):
    start: str
    end: str
    vehicle_height_m: float
    avoid_low_bridges: bool = True


# ------------------------------
# GEOCODER
# ------------------------------
def geocode(postcode: str):
    url = f"https://api.openrouteservice.org/geocode/search?api_key={ORS_API_KEY}&text={postcode}"
    r = requests.get(url)
    data = r.json()

    if "features" not in data or len(data["features"]) == 0:
        raise HTTPException(status_code=400, detail=f"Unable to geocode: {postcode}")

    lon, lat = data["features"][0]["geometry"]["coordinates"]
    return lat, lon


# ------------------------------
# BRIDGE CHECK
# ------------------------------
def nearest_bridge(lat, lon):
    bridges_df["distance"] = (
        (bridges_df["lat"] - lat)**2 + (bridges_df["lon"] - lon)**2
    )

    row = bridges_df.loc[bridges_df["distance"].idxmin()]
    return {
        "height_m": row["height_m"],
        "lat": row["lat"],
        "lon": row["lon"]
    }


# ------------------------------
# MAIN ROUTING ENDPOINT
# ------------------------------
@app.post("/api/route")
def route(req: RouteRequest):

    # 1) Geocode input
    start_lat, start_lon = geocode(req.start)
    end_lat, end_lon = geocode(req.end)

    # 2) Call ORS for HGV route
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}

    body = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
        "profile_params": {
            "restrictions": {
                "height": req.vehicle_height_m
            }
        }
    }

    ors = requests.post(ORS_URL, json=body, headers=headers)

    if ors.status_code != 200:
        raise HTTPException(status_code=500, detail=f"ORS error: {ors.text}")

    ors_json = ors.json()

    # 3) Extract summary
    summary = ors_json["routes"][0]["summary"]
    geom = ors_json["routes"][0]["geometry"]

    # 4) Check nearest bridge (simple version)
    nb = nearest_bridge(start_lat, start_lon)

    risk = "ok"
    if nb["height_m"] < req.vehicle_height_m:
        risk = "warning"

    return {
        "status": "ok",
        "geometry": geom,
        "summary": summary,
        "bridge_risk": risk,
        "nearest_bridge": nb,
        "engine": "RouteSafeAI v1.0"
    }


@app.get("/")
def root():
    return {
        "service": "RouteSafe-AI",
        "status": "ok",
        "message": "HGV low-bridge routing engine - use POST /api/route"
    }