import os
from typing import List, Dict, Tuple, Any, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from bridge_engine import BridgeEngine


# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

ORS_API_KEY = os.getenv("ORS_API_KEY")

if not ORS_API_KEY:
    print("WARNING: ORS_API_KEY environment variable is not set.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_CSV_PATH = os.path.join(BASE_DIR, "bridge_heights_clean.csv")

# BridgeEngine using your cleaned CSV
bridge_engine = BridgeEngine(BRIDGE_CSV_PATH)


# -------------------------------------------------------------------
# FastAPI setup
# -------------------------------------------------------------------

app = FastAPI(title="RouteSafe AI Backend", version="0.5")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------

class RouteRequest(BaseModel):
    depot_postcode: str
    stops: List[str]
    vehicle_height_m: float


class BridgeOut(BaseModel):
    name: str | None = None
    bridge_height_m: float
    distance_from_start_m: float
    lat: float
    lon: float


class RouteLegOut(BaseModel):
    from_postcode: str
    to_postcode: str
    distance_km: float
    duration_min: float
    vehicle_height_m: float
    low_bridges: List[BridgeOut]
    # main route (could pass near low bridge)
    geometry_main: List[List[float]] | None = None
    # alternative route avoiding a bubble around bridge
    geometry_alt: List[List[float]] | None = None
    alt_distance_km: float | None = None
    alt_duration_min: float | None = None


class RouteResponse(BaseModel):
    legs: List[RouteLegOut]


# -------------------------------------------------------------------
# Utility helpers
# -------------------------------------------------------------------

def geocode_postcode(pc: str) -> Tuple[float, float]:
    """
    Geocode a UK postcode via ORS -> (lat, lon).
    """
    if not ORS_API_KEY:
        raise HTTPException(500, "ORS_API_KEY missing")

    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": pc,
        "size": 1,
        "boundary.country": "GB",
    }

    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise HTTPException(502, f"ORS geocode failed: {r.text[:200]}")

    data = r.json()
    feats = data.get("features", [])
    if not feats:
        raise HTTPException(400, f"No geocoding result for {pc}")

    lon, lat = feats[0]["geometry"]["coordinates"]
    return float(lat), float(lon)


def _extract_summary_from_ors(data: Dict[str, Any], raw: str) -> Dict[str, Any]:
    """
    Extract distance, duration and geometry from ORS JSON/GeoJSON.
    Returns:
      {
        "distance_km": float,
        "duration_min": float,
        "geometry": [[lon, lat], ...]
      }
    """
    try:
        if "routes" in data:
            r0 = data["routes"][0]
            summary = r0["summary"]
            geom = r0.get("geometry")
            coords = geom.get("coordinates") if isinstance(geom, dict) else geom
        elif "features" in data:
            f0 = data["features"][0]
            summary = f0["properties"]["summary"]
            geom = f0.get("geometry")
            coords = geom.get("coordinates") if isinstance(geom, dict) else geom
        else:
            raise KeyError("Missing 'routes' or 'features'")
    except Exception as e:
        raise HTTPException(
            502,
            f"ORS parse error: {e} | Payload: {raw[:300]}",
        )

    distance_km = float(summary["distance"]) / 1000.0
    duration_min = float(summary["duration"]) / 60.0

    return {
        "distance_km": round(distance_km, 2),
        "duration_min": round(duration_min, 1),
        "geometry": coords,
    }


def get_hgv_route_metrics(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
    avoid_polygon: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Call ORS directions (HGV, then car fallback) using /geojson.
    ALWAYS returns geometry: if ORS doesn't send any, we fall back
    to a straight line from start -> end so Leaflet can still draw.
    """
    if not ORS_API_KEY:
        raise HTTPException(500, "ORS_API_KEY not configured")

    def call(profile: str):
        url = f"https://api.openrouteservice.org/v2/directions/{profile}/geojson"
        body: Dict[str, Any] = {
            "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
        }
        if avoid_polygon:
            body["options"] = {"avoid_polygons": avoid_polygon}

        headers = {
            "Authorization": ORS_API_KEY,
            "Content-Type": "application/json",
        }
        return profile, requests.post(url, json=body, headers=headers, timeout=25)

    last_err: str | None = None

    for profile in ["driving-hgv", "driving-car"]:
        p, resp = call(profile)

        if resp.status_code != 200:
            last_err = f"{p}: {resp.status_code} :: {resp.text[:200]}"
            continue

        raw = resp.text
        data: Dict[str, Any] = resp.json()
        out = _extract_summary_from_ors(data, raw)

        # Fallback geometry if ORS gives none
        if not out["geometry"]:
            out["geometry"] = [
                [float(start_lon), float(start_lat)],
                [float(end_lon), float(end_lat)],
            ]

        return out

    raise HTTPException(502, f"ORS failed: {last_err}")


# -------------------------------------------------------------------
# Routes (endpoints)
# -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root():
    # Simple OK text – your static frontend can live elsewhere
    return HTMLResponse("RouteSafe backend OK", 200)


@app.get("/health")
def health():
    return {"ok": True, "service": "RouteSafe AI backend"}


@app.post("/api/route", response_model=RouteResponse)
def api_route(req: RouteRequest):
    """
    Main entry point for the frontend.

    - Geocodes depot + stops
    - Builds legs in order
    - For each leg:
        * Gets ORS distance/time + geometry (main route)
        * Uses BridgeEngine.check_leg to detect nearest low bridge
        * If a bridge exists, asks ORS for an alternative with a small avoid polygon
    """
    if req.vehicle_height_m <= 0:
        raise HTTPException(400, "Vehicle height must be positive")

    if not req.depot_postcode.strip():
        raise HTTPException(400, "Depot postcode must not be empty")

    # Geocode depot
    depot_pc = req.depot_postcode.strip().upper()
    depot_lat, depot_lon = geocode_postcode(depot_pc)

    points: List[Tuple[float, float]] = [(depot_lat, depot_lon)]
    postcodes: List[str] = [depot_pc]

    # Geocode stops
    for pc in req.stops:
        pc_clean = pc.strip().upper()
        if not pc_clean:
            continue
        lat, lon = geocode_postcode(pc_clean)
        points.append((lat, lon))
        postcodes.append(pc_clean)

    if len(points) < 2:
        raise HTTPException(400, "Need at least one delivery postcode")

    legs: List[Dict[str, Any]] = []

    # Build each leg
    for i in range(len(points) - 1):
        start_lat, start_lon = points[i]
        end_lat, end_lon = points[i + 1]

        # MAIN ROUTE
        main = get_hgv_route_metrics(
            start_lon=start_lon,
            start_lat=start_lat,
            end_lon=end_lon,
            end_lat=end_lat,
        )
        geometry_main = main["geometry"]

        # BRIDGE CHECK via BridgeEngine
        br = bridge_engine.check_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=req.vehicle_height_m,
        )

        bridge_list: List[Dict[str, Any]] = []
        if br.nearest_bridge:
            bridge_list.append(
                {
                    "name": None,
                    "bridge_height_m": float(br.nearest_bridge.height_m),
                    "distance_from_start_m": float(br.nearest_distance_m or 0.0),
                    "lat": float(br.nearest_bridge.lat),
                    "lon": float(br.nearest_bridge.lon),
                }
            )

        # ALT ROUTE (if a bridge exists)
        geometry_alt: Optional[List[List[float]]] = None
        alt_dist: Optional[float] = None
        alt_time: Optional[float] = None

        if br.nearest_bridge:
            bx = float(br.nearest_bridge.lon)
            by = float(br.nearest_bridge.lat)

            # Simple square bubble around bridge (~120m radius)
            off = 0.0013
            avoid_poly: Dict[str, Any] = {
                "type": "Polygon",
                "coordinates": [[
                    [bx - off, by - off],
                    [bx + off, by - off],
                    [bx + off, by + off],
                    [bx - off, by + off],
                    [bx - off, by - off],
                ]],
            }

            try:
                alt = get_hgv_route_metrics(
                    start_lon=start_lon,
                    start_lat=start_lat,
                    end_lon=end_lon,
                    end_lat=end_lat,
                    avoid_polygon=avoid_poly,
                )
                geometry_alt = alt["geometry"]
                alt_dist = alt["distance_km"]
                alt_time = alt["duration_min"]
            except HTTPException as e:
                # If ORS can't find an alternative, we just skip alt
                print(f"[ALT ROUTE] ORS failed for leg {i}: {e.detail}")

        # Build leg dict
        legs.append(
            {
                "from_postcode": postcodes[i],
                "to_postcode": postcodes[i + 1],
                "distance_km": main["distance_km"],
                "duration_min": main["duration_min"],
                "vehicle_height_m": req.vehicle_height_m,
                "low_bridges": bridge_list,
                "geometry_main": geometry_main,
                "geometry_alt": geometry_alt,
                "alt_distance_km": alt_dist,
                "alt_duration_min": alt_time,
            }
        )

    return {"legs": legs}
```0