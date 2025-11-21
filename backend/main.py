import os
from typing import List, Dict, Tuple, Any

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

bridge_engine = BridgeEngine(BRIDGE_CSV_PATH)

# -------------------------------------------------------------------
# FastAPI setup
# -------------------------------------------------------------------

app = FastAPI(title="RouteSafe AI Backend", version="0.6")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)# -------------------------------------------------------------------
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
    geometry: List[List[float]] | None = None


class RouteResponse(BaseModel):
    legs: List[RouteLegOut]


# -------------------------------------------------------------------
# UI HTML (Leaflet map included)
# -------------------------------------------------------------------

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RouteSafe AI</title>

  <!-- Leaflet CSS -->
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""
  />

  <style>
    body { margin: 0; font-family: system-ui; background: #f3f4f6; }
    .page { max-width: 1100px; margin: 20px auto; padding: 10px; }
    .card { background: white; padding: 15px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,.1); margin-bottom: 20px; }
    .leg-map { height: 250px; border-radius: 10px; overflow: hidden; margin-top: 10px; border: 1px solid #ddd; }
    .pill-safe { background: #d1fae5; padding: 4px 8px; border-radius: 8px; color:#065f46; }
    .pill-risk { background: #fee2e2; padding: 4px 8px; border-radius: 8px; color:#991b1b; }
  </style>
</head>

<body>
<div class="page">
  <div class="card">
    <h2>Build HGV Route</h2>
    <form id="route-form">
      <label>Depot postcode</label>
      <input id="depot" value="LS270BN" />

      <label>Vehicle height (m)</label>
      <input id="height" type="number" step="0.1" value="4.0" />

      <label>Delivery postcodes (one per line)</label>
      <textarea id="stops">HD5 0RL</textarea>

      <button id="generate-btn">Generate</button>
      <div id="status"></div>
    </form>
  </div>

  <div class="card">
    <h2>Route legs</h2>
    <div id="legs-container"></div>
  </div>
</div>

<!-- Leaflet JS -->
<script
  src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-o9N1j7kGIC3bJlP2G8VHx0LhQv0vM1sM/5p3pqtIDJk="
  crossorigin=""></script>

<script>
const BACKEND_URL = "/api/route";// ---------------------------------------------------------------
// JS helpers
// ---------------------------------------------------------------

function setStatus(msg, error=false) {
    const st = document.getElementById("status");
    st.textContent = msg;
    st.style.color = error ? "red" : "green";
}

function renderLegMap(geometry, mapId) {
    if (!geometry || !geometry.length) return;

    // Convert ORS [[lon,lat], ...] → Leaflet [lat,lon]
    const latlngs = geometry.map(p => [p[1], p[0]]);

    const map = L.map(mapId, { zoomControl:false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
    }).addTo(map);

    const poly = L.polyline(latlngs, { color:"#0f62fe", weight:4 }).addTo(map);
    map.fitBounds(poly.getBounds(), { padding:[12,12] });
}

function renderLegs(legs) {
    const container = document.getElementById("legs-container");
    container.innerHTML = "";

    if (!legs || !legs.length) {
        container.innerHTML = "<p>No legs returned.</p>";
        return;
    }

    legs.forEach((leg, idx) => {
        const wrap = document.createElement("div");
        wrap.style.border = "1px solid #ddd";
        wrap.style.padding = "10px";
        wrap.style.borderRadius = "10px";
        wrap.style.marginBottom = "15px";

        const risky = leg.low_bridges && leg.low_bridges.length > 0;

        wrap.innerHTML = `
            <h3>Leg ${idx+1}: ${leg.from_postcode} → ${leg.to_postcode}</h3>
            <div>
                <span>Distance: ${leg.distance_km} km</span><br>
                <span>Time: ${leg.duration_min} min</span><br>
                <span>Vehicle height: ${leg.vehicle_height_m} m</span><br>
                <span class="${risky ? "pill-risk" : "pill-safe"}">
                    ${risky ? "LOW BRIDGE RISK" : "HGV SAFE"}
                </span>
            </div>
        `;

        // Map container
        const mapId = `map-${idx}`;
        const mapDiv = document.createElement("div");
        mapDiv.className = "leg-map";
        mapDiv.id = mapId;
        wrap.appendChild(mapDiv);

        container.appendChild(wrap);

        // Draw map
        if (leg.geometry) {
            renderLegMap(leg.geometry, mapId);
        } else {
            mapDiv.innerHTML = "<p>No geometry for this leg.</p>";
        }
    });
}


// ---------------------------------------------------------------
// Form handler
// ---------------------------------------------------------------

document.getElementById("route-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    setStatus("Loading…");

    const depot = document.getElementById("depot").value.trim();
    const height = parseFloat(document.getElementById("height").value);
    const stops = document
        .getElementById("stops")
        .value
        .split("\n")
        .map(x => x.trim())
        .filter(x => x.length > 0);

    if (!depot || stops.length === 0) {
        setStatus("Enter depot + at least one stop", true);
        return;
    }

    try {
        const resp = await fetch(BACKEND_URL, {
            method:"POST",
            headers:{ "Content-Type":"application/json" },
            body: JSON.stringify({
                depot_postcode: depot,
                vehicle_height_m: height,
                stops: stops
            })
        });

        const text = await resp.text();
        let data = null;
        try { data = JSON.parse(text); } catch {}

        if (!resp.ok) {
            setStatus(data?.detail || "Backend error", true);
            return;
        }

        renderLegs(data.legs);
        setStatus("Route generated.");
    }
    catch(err) {
        console.error(err);
        setStatus("Network or backend error.", true);
    }
});
</script>

</body>
</html>
"""
# -------------------------------------------------------------------
# ORS Helpers
# -------------------------------------------------------------------

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    """Return (lat, lon)."""
    if not ORS_API_KEY:
        raise HTTPException(500, "ORS_API_KEY missing")

    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": postcode,
        "size": 1,
        "boundary.country": "GB",
    }

    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise HTTPException(502, f"Geocode failed: {r.text[:200]}")

    data = r.json()
    feats = data.get("features", [])
    if not feats:
        raise HTTPException(400, f"No result for postcode {postcode}")

    lon, lat = feats[0]["geometry"]["coordinates"]
    return float(lat), float(lon)


def _extract_summary(data: Dict[str, Any], raw: str) -> Dict[str, Any]:
    """Extract distance, duration, geometry from ORS."""
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
            raise KeyError("No routes or features")
    except Exception as e:
        raise HTTPException(
            502,
            f"Unexpected ORS routing format: {e} | payload: {raw[:200]}"
        )

    return {
        "distance_km": round(float(summary["distance"]) / 1000, 2),
        "duration_min": round(float(summary["duration"]) / 60, 1),
        "geometry": coords,
    }


def get_route_metrics(start_lon, start_lat, end_lon, end_lat) -> Dict[str, Any]:
    """Call ORS driving-hgv → fallback driving-car."""
    if not ORS_API_KEY:
        raise HTTPException(500, "ORS_API_KEY missing")

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }
    body = {"coordinates": [[start_lon, start_lat], [end_lon, end_lat]]}

    for profile in ["driving-hgv", "driving-car"]:
        url = f"https://api.openrouteservice.org/v2/directions/{profile}"
        r = requests.post(url, json=body, headers=headers, timeout=25)

        if r.status_code != 200:
            continue

        return _extract_summary(r.json(), r.text)

    raise HTTPException(
        502,
        f"ORS failed for both HGV & CAR: {r.text[:200]}"
    )


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return HTMLResponse(content=HTML_PAGE)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/route", response_model=RouteResponse)
def api_route(req: RouteRequest):

    depot_pc = req.depot_postcode.strip().upper()
    stops_clean = [s.strip().upper() for s in req.stops if s.strip()]

    if not depot_pc:
        raise HTTPException(400, "Depot missing")

    if not stops_clean:
        raise HTTPException(400, "At least one stop required")

    # Geocode
    points: List[Tuple[float, float]] = []
    postcodes: List[str] = []

    depot_lat, depot_lon = geocode_postcode(depot_pc)
    points.append((depot_lat, depot_lon))
    postcodes.append(depot_pc)

    for pc in stops_clean:
        lat, lon = geocode_postcode(pc)
        points.append((lat, lon))
        postcodes.append(pc)

    # Legs
    legs_out: List[Dict[str, Any]] = []

    for i in range(len(points) - 1):
        start_lat, start_lon = points[i]
        end_lat, end_lon = points[i + 1]

        # ORS main route
        metrics = get_route_metrics(
            start_lon, start_lat, end_lon, end_lat
        )

        # Bridge check (nearest)
        result = bridge_engine.check_leg(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            vehicle_height_m=req.vehicle_height_m
        )

        low_bridges = []
        if result.nearest_bridge:
            low_bridges.append({
                "name": None,
                "bridge_height_m": float(result.nearest_bridge.height_m),
                "distance_from_start_m": float(result.nearest_distance_m or 0),
                "lat": float(result.nearest_bridge.lat),
                "lon": float(result.nearest_bridge.lon),
            })

        legs_out.append({
            "from_postcode": postcodes[i],
            "to_postcode": postcodes[i + 1],
            "distance_km": metrics["distance_km"],
            "duration_min": metrics["duration_min"],
            "vehicle_height_m": req.vehicle_height_m,
            "low_bridges": low_bridges,
            "geometry": metrics["geometry"],
        })

    return {"legs": legs_out}