from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import requests
import math
import os
import io

app = FastAPI()

# ===================================
# CORS
# ===================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================================
# Load ORS API Key
# ===================================
ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    raise RuntimeError("ORS_API_KEY is missing from environment variables!")


# ===================================
# Load Bridge Dataset
# ===================================
BRIDGE_FILE = "bridge_heights_clean.csv"

try:
    df_bridges = pd.read_csv(BRIDGE_FILE)
except Exception as e:
    raise RuntimeError(f"Could not load bridge CSV: {e}")

# Ensure correct columns
required_cols = {"lat", "lon", "height_m"}
missing = required_cols - set(df_bridges.columns)
if missing:
    raise RuntimeError(f"Bridge CSV missing columns: {missing}")

# Clean rows with missing heights
df_bridges = df_bridges.dropna(subset=["lat", "lon", "height_m"])


# ===================================
# Check Nearby Bridges via Haversine
# ===================================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi/2)**2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2)
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def check_bridge_clearance(lat, lon, vehicle_height_m, radius_km=0.2):
    """
    Returns the FIRST low bridge found within radius_km.
    If none, returns None.
    """
    for _, row in df_bridges.iterrows():
        dist = haversine(lat, lon, row["lat"], row["lon"])
        if dist <= radius_km:
            if row["height_m"] < vehicle_height_m:
                return {
                    "bridge_lat": row["lat"],
                    "bridge_lon": row["lon"],
                    "bridge_height_m": row["height_m"],
                    "distance_km": dist
                }
    return None


# ===================================
# ORS Truck Routing
# ===================================
def ors_truck_route(start, end, height_m):
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv"

    payload = {
        "coordinates": [
            [start["lon"], start["lat"]],
            [end["lon"], end["lat"]]
        ],
        "profile_params": {
            "restrictions": {
                "height": height_m
            }
        }
    }

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"ORS error: {response.text}")

    return response.json()


# ===================================
# API ROUTE: /route
# ===================================
@app.post("/route")
async def generate_route(data: dict):
    try:
        start_pc = data["start"]
        stops = data["stops"]
        vehicle_height_m = float(data["vehicle_height_m"])
    except:
        raise HTTPException(status_code=400, detail="Invalid input format")

    # Geo lookup via ORS geocode
    def geocode(postcode):
        url = f"https://api.openrouteservice.org/geocode/search?api_key={ORS_API_KEY}&text={postcode}"
        r = requests.get(url)
        j = r.json()
        if "features" not in j or len(j["features"]) == 0:
            raise HTTPException(status_code=400, detail=f"Cannot geocode {postcode}")
        coords = j["features"][0]["geometry"]["coordinates"]
        return {"lon": coords[0], "lat": coords[1]}

    start = geocode(start_pc)
    coords_list = [geocode(pc) for pc in stops]

    legs = []

    # Go through each leg
    prev = start
    for stop in coords_list:
        # Run truck route
        route_json = ors_truck_route(prev, stop, vehicle_height_m)

        # Detect bridge warnings along the path
        warnings = []
        for seg in route_json["features"][0]["geometry"]["coordinates"]:
            lon, lat = seg[0], seg[1]
            w = check_bridge_clearance(lat, lon, vehicle_height_m)
            if w:
                warnings.append(w)

        legs.append({
            "from": prev,
            "to": stop,
            "warnings": warnings,
            "maps_link": f"https://www.google.com/maps/dir/{prev['lat']},{prev['lon']}/{stop['lat']},{stop['lon']}/"
        })

        prev = stop

    return {"legs": legs, "vehicle_height_m": vehicle_height_m}