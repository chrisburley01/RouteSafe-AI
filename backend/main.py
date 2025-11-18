# backend/main.py
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List

app = FastAPI(title="RouteSafe AI Backend", version="0.1")


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


@app.get("/")
def read_root():
    return {"status": "ok", "service": "RouteSafe AI"}


@app.post("/route", response_model=RouteResponse)
def route(request: RouteRequest):
    """
    Stub: returns fake distances so frontend works.
    Later this will:
    - geocode postcodes
    - call HGV-safe router (OSM/GraphHopper/etc.)
    - compute real distances & durations
    """
    all_points = [request.depot_postcode] + request.delivery_postcodes

    legs: List[Leg] = []
    total_distance = 0.0
    total_duration = 0.0

    for i in range(len(all_points) - 1):
        from_pc = all_points[i]
        to_pc = all_points[i + 1]

        # Fake distances so UI works – replace with real routing logic.
        distance_km = 10.0 + i * 2.5
        duration_min = distance_km / 60.0 * 60.0  # pretend 60 km/h

        leg = Leg(
            from_=from_pc,
            to=to_pc,
            distance_km=distance_km,
            duration_min=duration_min,
            near_height_limit=False,
        )

        legs.append(leg)
        total_distance += distance_km
        total_duration += duration_min

    return RouteResponse(
        total_distance_km=total_distance,
        total_duration_min=total_duration,
        legs=legs,
    )