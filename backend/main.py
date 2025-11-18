# main.py

from typing import List

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI(title="RouteSafe AI", version="0.1")

# Allow your GitHub Pages front end
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


# ---------- ROUTES ---------- #

@app.get("/")
def root():
    return {"status": "ok", "service": "RouteSafe AI", "version": "0.1"}


@app.post("/route", response_model=RouteResponse)
def route(request: RouteRequest):
    """
    TEMP: no real mapping yet.
    Just treats each leg as 10km / 15min so we can prove
    the frontend <-> backend connection works.
    """
    # Clean up postcodes list
    points = [request.depot_postcode.strip().upper()]
    points += [pc.strip().upper() for pc in request.delivery_postcodes if pc.strip()]

    if len(points) < 2:
        # Need at least depot + one stop
        return RouteResponse(total_distance_km=0.0, total_duration_min=0.0, legs=[])

    legs: List[Leg] = []
    total_distance = 0.0
    total_duration = 0.0

    for i in range(len(points) - 1):
        frm = points[i]
        to = points[i + 1]

        # Dummy values – 10km and 15min per leg
        distance_km = 10.0
        duration_min = 15.0

        total_distance += distance_km
        total_duration += duration_min

        legs.append(
            Leg(
                from_=frm,
                to=to,
                distance_km=distance_km,
                duration_min=duration_min,
                near_height_limit=False,
            )
        )

    return RouteResponse(
        total_distance_km=total_distance,
        total_duration_min=total_duration,
        legs=legs,
    )


# Stub so the /ocr call doesn't crash yet
@app.post("/ocr")
async def ocr_stub(file: UploadFile = File(...)):
    return {"raw_text": "", "postcodes": []}