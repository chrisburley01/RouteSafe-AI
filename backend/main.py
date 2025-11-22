import os
import math
import pandas as pd
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from bridge_engine import BridgeEngine

app = FastAPI()

# Allow all origins (frontend on GitHub Pages)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ORS_API_KEY = os.getenv("ORS_API_KEY", "")
bridge_engine = BridgeEngine(csv_path="bridge_heights_clean.csv")

# -----------------------------------------------------------
# Helper – extract first non-empty value from many variations
# -----------------------------------------------------------
def pick(data: dict, keys: list):
    for k in keys:
        if k in data and data[k] not in ("", None):
            return data[k]
    return None


# -----------------------------------------------------------
# Root check
# -----------------------------------------------------------
@app.get("/")
def root():
    return {"detail": "RouteSafe API is running. POST to /api/route."}


# -----------------------------------------------------------
# Main route generation endpoint
# -----------------------------------------------------------
@app.post("/api/route")
async def generate_route(request: Request):

    data = await request.json()

    # --------
    # INPUTS
    # --------
    vehicle_height = pick(
        data,
        [
            "vehicleHeight",
            "vehicle_height",
            "vehicle_height_m",
            "height",
            "hgv_height",
        ],
    )

    origin = pick(
        data,
        [
            "depotPostcode",
            "depot_postcode",
            "originPostcode",
            "origin_postcode",
            "startPostcode",
            "start_postcode",
        ],
    )

    postcodes_raw = pick(
        data,
        [
            "deliveryPostcodes",
            "delivery_postcodes",
            "postcodes",
            "drops",
        ],
    )

    if not origin:
        return {"error": "depot/origin postcode is required"}
    if not postcodes_raw:
        return {"error": "at least one delivery postcode is required"}
    if not vehicle_height:
        return {"error": "vehicle height is required"}

    # normalise list
    if isinstance(postcodes_raw, str):
        delivery_list = [
            p.strip() for p in postcodes_raw.split("\n") if p.strip()
        ]
    else:
        delivery_list = postcodes_raw

    # ------------------------------------------------------
    # Build ordered route: origin → each drop in sequence
    # ------------------------------------------------------
    route_points = [origin] + delivery_list

    legs_output = []

    for i in range(len(route_points) - 1):
        start_pc = route_points[i]
        end_pc = route_points[i + 1]

        # 1) Geocode both ends using ORS
        geocode_url = "https://api.openrouteservice.org/geocode/search"

        def geocode(pc):
            r = requests.get(
                geocode_url,
                params={"api_key": ORS_API_KEY, "text": pc, "boundary.country": "GB"},
                timeout=10,
            )
            r.raise_for_status()
            js = r.json()
            coords = js["features"][0]["geometry"]["coordinates"]
            return coords[1], coords[0]  # lat, lon

        try:
            start_lat, start_lon = geocode(start_pc)
            end_lat, end_lon = geocode(end_pc)
        except Exception as e:
            legs_output.append(
                {
                    "index": i,
                    "start_postcode": start_pc,
                    "end_postcode": end_pc,
                    "error": f"Failed to geocode: {str(e)}",
                }
            )
            continue

        # 2) ORS routing
        route_url = "https://api.openrouteservice.org/v2/directions/driving-hgv"
        body = {
            "coordinates": [
                [start_lon, start_lat],
                [end_lon, end_lat],
            ]
        }

        try:
            r = requests.post(
                route_url,
                json=body,
                headers={"Authorization": ORS_API_KEY},
                timeout=15,
            )
            r.raise_for_status()
            js = r.json()
            summary = js["routes"][0]["summary"]
            distance_km = summary["distance"] / 1000
            duration_min = summary["duration"] / 60
        except Exception as e:
            legs_output.append(
                {
                    "index": i,
                    "start_postcode": start_pc,
                    "end_postcode": end_pc,
                    "error": f"ORS routing failed: {str(e)}",
                }
            )
            continue

        # 3) Bridge check (straight line)
        result = bridge_engine.check_leg(
            (start_lat, start_lon),
            (end_lat, end_lon),
            float(vehicle_height),
        )

        if result.nearest_bridge:
            msg = (
                f"Nearest bridge {result.nearest_bridge.height_m}m "
                f"{result.nearest_distance_m:.0f}m from route"
            )
        else:
            msg = "No bridge risk detected"

        legs_output.append(
            {
                "index": i,
                "start_postcode": start_pc,
                "end_postcode": end_pc,
                "distance_km": round(distance_km, 2),
                "duration_min": round(duration_min, 1),
                "vehicle_height_m": float(vehicle_height),
                "has_conflict": result.has_conflict,
                "near_height_limit": result.near_height_limit,
                "bridge_message": msg,
                "safety_label": (
                    "RED – unsafe"
                    if result.has_conflict
                    else ("AMBER – caution" if result.near_height_limit else "GREEN – clear")
                ),
                "google_maps_url": f"https://www.google.com/maps/dir/{start_pc}/{end_pc}",
                "bridge_points": []
                if not result.nearest_bridge
                else [
                    {
                        "lat": result.nearest_bridge.lat,
                        "lon": result.nearest_bridge.lon,
                        "height_m": result.nearest_bridge.height_m,
                    }
                ],
            }
        )

    return {"legs": legs_output}