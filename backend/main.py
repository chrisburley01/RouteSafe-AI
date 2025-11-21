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

app = FastAPI(title="RouteSafe AI Backend", version="0.4")

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
    geometry: List[List[float]] | None = None            # [[lon,lat],...]
    alt_distance_km: float | None = None                 # alternative (if any)
    alt_duration_min: float | None = None
    alt_geometry: List[List[float]] | None = None


class RouteResponse(BaseModel):
    legs: List[RouteLegOut]


# -------------------------------------------------------------------
# UI (Leaflet + two lines per risky leg: red = original, green = alt)
# -------------------------------------------------------------------

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>RouteSafe AI · Prototype</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<style>
:root{--primary:#002c77;--primary-dark:#0f2353;--bg:#f3f4f6;--card-bg:#fff;--border:#e5e7eb;--muted:#6b7280;--radius-lg:16px;--shadow-card:0 14px 35px rgba(15,35,83,.14)}
*{box-sizing:border-box;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
body{margin:0;background:var(--bg);color:#111827}
.hero{background:radial-gradient(circle at top left,#1d4ed8,#020617);color:#e5e7eb;padding:1.5rem 1rem 1.8rem}
.hero-inner{max-width:1100px;margin:0 auto}
.brand-row{display:flex;align-items:center;gap:.7rem;margin-bottom:.4rem}
.brand-logo{width:36px;height:36px;border-radius:10px;background:#16a34a;display:flex;align-items:center;justify-content:center}
.brand-title{font-weight:600}
.hero h1{margin:0;font-size:1.9rem;font-weight:600}
.hero p{margin:.4rem 0 0;font-size:.93rem;color:#cbd5f5;max-width:620px}
.version{margin-top:.3rem;font-size:.8rem;color:#9ca3af}
.page{max-width:1100px;margin:-1.5rem auto 0;padding:0 1rem 2.5rem}
.layout{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1.1fr);gap:1.2rem}
@media(max-width:900px){.layout{grid-template-columns:minmax(0,1fr)}}
.card{background:var(--card-bg);border-radius:var(--radius-lg);padding:1.2rem 1.3rem 1.4rem;box-shadow:var(--shadow-card);border:1px solid rgba(15,35,83,.06)}
.card h2{margin:0 0 .3rem;font-size:1.1rem;color:var(--primary-dark)}
.card-subtitle{margin:0 0 .8rem;font-size:.85rem;color:var(--muted)}
.field{margin-bottom:.85rem}
label{display:block;font-size:.85rem;margin-bottom:.25rem;font-weight:500;color:#374151}
input,textarea{width:100%;padding:.6rem .65rem;border-radius:10px;border:1px solid #d1d5db;font-size:.9rem;background:#f9fafb}
input:focus,textarea:focus{border-color:var(--primary);box-shadow:0 0 0 1px rgba(0,44,119,.25);background:#fff}
textarea{min-height:130px;resize:vertical;white-space:pre}
.hint{font-size:.78rem;color:var(--muted);margin-top:.25rem}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.35rem;padding:.65rem 1.35rem;border-radius:999px;border:none;background:#00b894;color:#fff;font-size:.9rem;font-weight:600;cursor:pointer;box-shadow:0 10px 24px rgba(0,184,148,.35);margin-top:.3rem}
.btn:hover{background:#02a184}
.status{margin-top:.8rem;font-size:.83rem}
.status-error{background:#fee2e2;color:#b91c1c;border-radius:10px;padding:.65rem .75rem}
.legs-list{margin-top:.5rem;border-top:1px solid #e5e7eb;padding-top:.6rem;max-height:460px;overflow-y:auto;font-size:.86rem}
.leg{border-radius:10px;border:1px solid #e5e7eb;padding:.6rem .65rem;margin-bottom:.75rem;background:#f9fafb}
.leg-header{display:flex;justify-content:space-between;margin-bottom:.3rem}
.leg-title{font-weight:600}
.pill{padding:.05rem .55rem;border-radius:999px;font-size:.7rem;font-weight:600;text-transform:uppercase}
.pill-safe{background:#d1fae5;color:#047857}
.pill-risk{background:#fef3c7;color:#92400e}
.leg-meta{display:flex;flex-wrap:wrap;gap:.4rem .8rem;font-size:.78rem;color:#4b5563;margin-bottom:.3rem}
.leg-map{margin-top:.45rem;height:220px;border-radius:10px;overflow:hidden;border:1px solid #e5e7eb}
.legend{font-size:.75rem;color:#4b5563;margin-top:.35rem}
</style>
</head>
<body>
  <div class="hero">
    <div class="hero-inner">
      <div class="brand-row">
        <div class="brand-logo">🛣️</div>
        <div class="brand-title">RouteSafe AI</div>
      </div>
      <h1>Build a safe HGV route</h1>
      <p>Checks each leg for low bridges. Red = original route; Green = safe alternative (when available).</p>
      <div class="version">Prototype v0.4 | Internal Use Only</div>
    </div>
  </div>

  <div class="page">
    <div class="layout">
      <div class="card">
        <h2>Route details</h2>
        <p class="card-subtitle">Enter depot, height and postcodes in order.</p>
        <form id="route-form">
          <div class="field">
            <label>Depot postcode</label>
            <input id="depot" type="text" value="LS270BN" />
          </div>
          <div class="field">
            <label>Vehicle / trailer height (m)</label>
            <input id="height" type="number" step="0.1" value="4.0" />
            <div class="hint">Full running height.</div>
          </div>
          <div class="field">
            <label>Delivery postcodes in order</label>
            <textarea id="stops">Hd5 0rl</textarea>
            <div class="hint">One postcode per line.</div>
          </div>
          <button class="btn" id="generate-btn">Generate safe legs</button>
          <div id="status" class="status"></div>
        </form>
      </div>

      <div class="card">
        <h2>Route legs</h2>
        <p class="card-subtitle">Each leg checked for low bridges.</p>
        <div id="legs-container" class="legs-list">
          <div class="hint">Enter route on the left and click <strong>Generate</strong>.</div>
        </div>
      </div>
    </div>
    <footer class="hint">Data source: OpenRouteService + internal UK low bridge dataset.</footer>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-o9N1j7kGIC3bJlP2G8VHx0LhQv0vM1sM/5p3pqtIDJk=" crossorigin=""></script>
  <script>
    const BACKEND_URL = "/api/route";
    const form = document.getElementById("route-form");
    const statusEl = document.getElementById("status");
    const legsContainer = document.getElementById("legs-container");
    const generateBtn = document.getElementById("generate-btn");

    function setStatus(msg, type="info"){
      statusEl.textContent = msg || "";
      statusEl.className = msg ? (type==="error" ? "status status-error" : "status") : "status";
    }

    function mkMapPolyline(latLngs, color){
      return L.polyline(latLngs, {color, weight:5});
    }

    function toLatLngs(geometry){
      if(!geometry) return [];
      return geometry.map(([lon,lat]) => [lat,lon]);
    }

    function renderLegs(legs){
      legsContainer.innerHTML = "";
      if(!legs || !legs.length){
        legsContainer.innerHTML = '<div class="hint">No legs returned from backend.</div>';
        return;
      }
      legs.forEach((leg, idx) => {
        const risky = (leg.low_bridges||[]).length > 0;

        const wrap = document.createElement("div");
        wrap.className = "leg";

        const head = document.createElement("div");
        head.className = "leg-header";
        head.innerHTML = \`
          <div class="leg-title">Leg \${idx+1}: \${leg.from_postcode} → \${leg.to_postcode}</div>
          <div class="pill \${risky ? "pill-risk":"pill-safe"}">\${risky ? "LOW BRIDGE(S)":"HGV SAFE"}</div>\`;
        wrap.appendChild(head);

        const meta = document.createElement("div");
        meta.className = "leg-meta";
        meta.innerHTML = \`
          <span>Distance: \${leg.distance_km} km</span>
          <span>Time: \${leg.duration_min} min</span>
          <span>Vehicle height: \${leg.vehicle_height_m} m</span>\`;
        wrap.appendChild(meta);

        if(risky){
          const warn = document.createElement("div");
          const b = leg.low_bridges[0];
          warn.className = "hint";
          warn.textContent = \`\${leg.low_bridges.length} low bridge(s). Nearest ~\${(b.bridge_height_m).toFixed(2)} m.\`;
          wrap.appendChild(warn);
        }

        const mapId = "map-"+idx;
        const mapDiv = document.createElement("div");
        mapDiv.className = "leg-map";
        mapDiv.id = mapId;
        wrap.appendChild(mapDiv);

        const legend = document.createElement("div");
        legend.className = "legend";
        legend.innerHTML = risky && leg.alt_geometry ? "Red = original (risk). Green = alternative (avoids low bridge)." : "Route line.";
        wrap.appendChild(legend);

        legsContainer.appendChild(wrap);

        // draw map
        const map = L.map(mapId,{zoomControl:false,attributionControl:false});
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19}).addTo(map);

        const mainLine = toLatLngs(leg.geometry);
        if(mainLine.length){
          mkMapPolyline(mainLine, risky ? "#dc2626" : "#16a34a").addTo(map);
          map.fitBounds(L.polyline(mainLine).getBounds(), {padding:[10,10]});
        } else {
          mapDiv.innerHTML = '<div class="hint" style="padding:.6rem;">No map data available for this leg.</div>';
        }

        if(risky && leg.alt_geometry){
          const altLine = toLatLngs(leg.alt_geometry);
          if(altLine.length){
            mkMapPolyline(altLine, "#16a34a").addTo(map);
          }
        }
      });
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const depot = document.getElementById("depot").value.trim();
      const height = parseFloat(document.getElementById("height").value);
      const stops = document.getElementById("stops").value.split("\\n").map(x=>x.trim()).filter(Boolean);

      if(!depot || !stops.length){ setStatus("Enter depot + at least one postcode.","error"); return; }
      if(!height || height<=0){ setStatus("Vehicle height must be a positive number in metres.","error"); return; }

      setStatus("Contacting backend…"); generateBtn.disabled = true;
      try{
        const resp = await fetch(BACKEND_URL,{method:"POST",headers:{"Content-Type":"application/json"},
          body: JSON.stringify({depot_postcode: depot, vehicle_height_m: height, stops})});
        const text = await resp.text(); let data=null; try{ data = JSON.parse(text); }catch{}
        if(!resp.ok){ throw new Error((data && (data.detail||data.message)) || "Status "+resp.status); }
        renderLegs(data.legs); setStatus("Route generated successfully.");
      }catch(err){ console.error(err); setStatus("Backend error: "+(err.message||err),"error");
        legsContainer.innerHTML = '<div class="hint">No results – backend returned an error.</div>';
      }finally{ generateBtn.disabled = false; }
    });
  </script>
</body>
</html>
"""

# -------------------------------------------------------------------
# ORS helpers
# -------------------------------------------------------------------

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    if not ORS_API_KEY:
        raise HTTPException(status_code=500, detail="ORS_API_KEY is not configured on the server.")
    text = postcode.strip().upper()
    if not text:
        raise HTTPException(status_code=400, detail="Empty postcode supplied for geocoding.")
    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": text, "size": 1, "boundary.country": "GB"}
    try:
        resp = requests.get(url, params=params, timeout=20)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error calling ORS geocoding for '{text}': {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"ORS geocoding failed for '{text}' (status {resp.status_code}): {resp.text[:300]}")
    features = (resp.json().get("features") or [])
    if not features:
        raise HTTPException(status_code=400, detail=f"No geocoding result found for postcode '{text}'.")
    lon, lat = features[0]["geometry"]["coordinates"]
    return float(lat), float(lon)

def _coerce_geometry_coords(geom: Any) -> List[List[float]] | None:
    if isinstance(geom, dict):
        geom = geom.get("coordinates")
    if not isinstance(geom, list):
        return None
    out: List[List[float]] = []
    for pt in geom:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            try:
                out.append([float(pt[0]), float(pt[1])])
            except (TypeError, ValueError):
                pass
    return out or None

def _extract_summary_from_ors(data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    try:
        if "routes" in data:
            route0 = data["routes"][0]
            summary = route0["summary"]
            geometry_coords = _coerce_geometry_coords(route0.get("geometry"))
        elif "features" in data:
            feat0 = data["features"][0]
            summary = feat0["properties"]["summary"]
            geometry_coords = _coerce_geometry_coords(feat0.get("geometry"))
        else:
            raise KeyError("Neither 'routes' nor 'features' present")
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(status_code=502, detail=f"Unexpected routing response from ORS: {e} | payload: {raw_text[:300]}")
    distance_km = float(summary["distance"]) / 1000.0
    duration_min = float(summary["duration"]) / 60.0
    return {"distance_km": round(distance_km, 2), "duration_min": round(duration_min, 1), "geometry": geometry_coords}

def _call_ors_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float, options: Dict[str, Any] | None = None):
    if not ORS_API_KEY:
        raise HTTPException(status_code=500, detail="ORS_API_KEY is not configured on the server.")
    url = "https://api.openrouteservice.org/v2/directions/{profile}"
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    body = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
        "geometry": True,                      # ensure geometry included
        "geometry_format": "geojson",          # return as GeoJSON coords
        "geometry_simplify": False,
    }
    if options:
        body["options"] = options
    def do(profile: str):
        resp = requests.post(url.format(profile=profile), json=body, headers=headers, timeout=25)
        return profile, resp
    return do

def get_hgv_route_metrics(start_lon: float, start_lat: float, end_lon: float, end_lat: float, options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    do = _call_ors_route(start_lon, start_lat, end_lon, end_lat, options)
    last_err = None
    for profile in ["driving-hgv", "driving-car"]:
        profile_used, resp = do(profile)
        if resp.status_code != 200:
            last_err = f"{profile_used} status {resp.status_code}: {resp.text[:300]}"
            continue
        return _extract_summary_from_ors(resp.json(), resp.text)
    raise HTTPException(status_code=502, detail=f"Routing failed via ORS: {last_err or 'no response'}")

# quick helper to build a small avoid polygon (~200 m circle) around lat/lon
def _avoid_polygon_around(lat: float, lon: float, radius_m: float = 200.0, steps: int = 16) -> Dict[str, Any]:
    # very rough meters->degrees conversion
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.2, abs(__import__("math").cos(__import__("math").radians(lat)))))
    pts = []
    for i in range(steps):
        ang = 2*__import__("math").pi*i/steps
        pts.append([lon + dlon*__import__("math").cos(ang), lat + dlat*__import__("math").sin(ang)])
    pts.append(pts[0])  # close polygon
    return {"type":"Polygon","coordinates":[pts]}

# -------------------------------------------------------------------
# API
# -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return HTMLResponse(content=HTML_PAGE, status_code=200)

@app.get("/health")
def health():
    return {"ok": True, "service": "RouteSafe AI backend"}

@app.post("/api/route", response_model=RouteResponse)
def api_route(req: RouteRequest):
    try:
        if not ORS_API_KEY:
            raise HTTPException(status_code=500, detail="ORS_API_KEY is not configured on the server.")

        depot_pc = req.depot_postcode.strip().upper()
        stops_clean = [s.strip().upper() for s in req.stops if s.strip()]
        if not depot_pc: raise HTTPException(status_code=400, detail="Depot postcode must not be empty.")
        if not stops_clean: raise HTTPException(status_code=400, detail="At least one delivery postcode is required.")
        if req.vehicle_height_m <= 0: raise HTTPException(status_code=400, detail="Vehicle height must be a positive number in metres.")

        # geocode
        points: List[Tuple[float, float]] = []
        postcodes: List[str] = []
        depot_lat, depot_lon = geocode_postcode(depot_pc)
        points.append((depot_lat, depot_lon)); postcodes.append(depot_pc)
        for pc in stops_clean:
            lat, lon = geocode_postcode(pc)
            points.append((lat, lon)); postcodes.append(pc)

        legs_out: List[Dict[str, Any]] = []
        for idx in range(len(points)-1):
            start_lat, start_lon = points[idx]
            end_lat, end_lon = points[idx+1]

            metrics = get_hgv_route_metrics(start_lon, start_lat, end_lon, end_lat)

            # check bridges along straight-line leg (fast approximation)
            result = bridge_engine.check_leg(
                start_lat=start_lat, start_lon=start_lon,
                end_lat=end_lat, end_lon=end_lon,
                vehicle_height_m=req.vehicle_height_m,
            )

            low_bridges: List[Dict[str, Any]] = []
            alt_metrics = {"distance_km": None, "duration_min": None, "geometry": None}

            if result.nearest_bridge is not None:
                low_bridges.append({
                    "name": None,
                    "bridge_height_m": float(result.nearest_bridge.height_m),
                    "distance_from_start_m": float(result.nearest_distance_m or 0.0),
                    "lat": float(result.nearest_bridge.lat),
                    "lon": float(result.nearest_bridge.lon),
                })
                # ask ORS for an alternative that avoids a small area around the bridge
                avoid_poly = _avoid_polygon_around(result.nearest_bridge.lat, result.nearest_bridge.lon, 200.0)
                try:
                    alt = get_hgv_route_metrics(
                        start_lon, start_lat, end_lon, end_lat,
                        options={"avoid_polygons": avoid_poly}
                    )
                    alt_metrics = alt
                except Exception:
                    pass  # if ORS can't find an alt, we just skip it

            legs_out.append({
                "from_postcode": postcodes[idx],
                "to_postcode": postcodes[idx+1],
                "distance_km": metrics["distance_km"],
                "duration_min": metrics["duration_min"],
                "vehicle_height_m": req.vehicle_height_m,
                "low_bridges": low_bridges,
                "geometry": metrics.get("geometry"),
                "alt_distance_km": alt_metrics["distance_km"],
                "alt_duration_min": alt_metrics["duration_min"],
                "alt_geometry": alt_metrics.get("geometry"),
            })

        return {"legs": legs_out}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected server error: {e}")