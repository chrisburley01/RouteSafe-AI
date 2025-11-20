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

app = FastAPI(title="RouteSafe AI Backend", version="0.2")

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


class RouteResponse(BaseModel):
    legs: List[RouteLegOut]


# -------------------------------------------------------------------
# UI HTML (same look as your working prototype)
# -------------------------------------------------------------------

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RouteSafe AI · Prototype</title>
  <style>
    :root {
      --primary: #002c77;
      --primary-dark: #0f2353;
      --bg: #f3f4f6;
      --card-bg: #ffffff;
      --border: #d1d5db;
      --muted: #6b7280;
      --danger-bg: #fee2e2;
      --danger-text: #b91c1c;
      --radius-lg: 16px;
      --shadow-card: 0 14px 35px rgba(15, 35, 83, 0.14);
    }
    * {
      box-sizing: border-box;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
        sans-serif;
    }
    body {
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: #111827;
    }
    .hero {
      background: radial-gradient(circle at top left, #1d4ed8, #020617);
      color: #e5e7eb;
      padding: 1.5rem 1rem 1.8rem;
    }
    .hero-inner {
      max-width: 1100px;
      margin: 0 auto;
    }
    .brand-row {
      display: flex;
      align-items: center;
      gap: 0.7rem;
      margin-bottom: 0.4rem;
    }
    .brand-logo {
      width: 36px;
      height: 36px;
      border-radius: 10px;
      background: #16a34a;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.2rem;
    }
    .brand-title {
      font-size: 1.2rem;
      font-weight: 600;
    }
    .hero h1 {
      margin: 0;
      font-size: 1.9rem;
      font-weight: 600;
    }
    .hero p {
      margin: 0.4rem 0 0;
      font-size: 0.93rem;
      color: #cbd5f5;
      max-width: 620px;
    }
    .version {
      margin-top: 0.3rem;
      font-size: 0.8rem;
      color: #9ca3af;
    }
    .page {
      max-width: 1100px;
      margin: -1.5rem auto 0;
      padding: 0 1rem 2.5rem;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.1fr);
      gap: 1.2rem;
    }
    @media (max-width: 900px) {
      .layout {
        grid-template-columns: minmax(0, 1fr);
      }
    }
    .card {
      background: var(--card-bg);
      border-radius: var(--radius-lg);
      padding: 1.2rem 1.3rem 1.4rem;
      box-shadow: var(--shadow-card);
      border: 1px solid rgba(15, 35, 83, 0.06);
    }
    .card h2 {
      margin: 0 0 0.3rem;
      font-size: 1.1rem;
      color: var(--primary-dark);
    }
    .card-subtitle {
      margin: 0 0 0.8rem;
      font-size: 0.85rem;
      color: var(--muted);
    }
    .field {
      margin-bottom: 0.85rem;
    }
    label {
      display: block;
      font-size: 0.85rem;
      margin-bottom: 0.25rem;
      font-weight: 500;
      color: #374151;
    }
    input,
    textarea {
      width: 100%;
      padding: 0.6rem 0.65rem;
      border-radius: 10px;
      border: 1px solid var(--border);
      font-size: 0.9rem;
      background: #f9fafb;
    }
    input:focus,
    textarea:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 1px rgba(0, 44, 119, 0.25);
      background: #ffffff;
    }
    textarea {
      min-height: 130px;
      resize: vertical;
      white-space: pre;
    }
    .hint {
      font-size: 0.78rem;
      color: var(--muted);
      margin-top: 0.25rem;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.35rem;
      padding: 0.65rem 1.35rem;
      border-radius: 999px;
      border: none;
      background: #00b894;
      color: #ffffff;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 10px 24px rgba(0, 184, 148, 0.35);
      margin-top: 0.3rem;
    }
    .btn:hover {
      background: #02a184;
      box-shadow: 0 12px 26px rgba(0, 184, 148, 0.4);
      transform: translateY(-1px);
    }
    .btn:disabled {
      opacity: 0.65;
      cursor: default;
    }
    .status {
      margin-top: 0.8rem;
      font-size: 0.83rem;
    }
    .status-error {
      background: var(--danger-bg);
      color: var(--danger-text);
      border-radius: 10px;
      padding: 0.65rem 0.75rem;
    }
    .status-ok {
      color: #047857;
    }
    .legs-list {
      margin-top: 0.5rem;
      border-top: 1px solid #e5e7eb;
      padding-top: 0.6rem;
      max-height: 420px;
      overflow-y: auto;
      font-size: 0.86rem;
    }
    .leg {
      border-radius: 10px;
      border: 1px solid #e5e7eb;
      padding: 0.6rem 0.65rem;
      margin-bottom: 0.5rem;
      background: #f9fafb;
    }
    .leg-header {
      display: flex;
      justify-content: space-between;
      margin-bottom: 0.3rem;
    }
    .leg-title {
      font-weight: 600;
      color: #111827;
      font-size: 0.92rem;
    }
    .pill {
      padding: 0.05rem 0.55rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
    }
    .pill-safe {
      background: #d1fae5;
      color: #047857;
    }
    .pill-risk {
      background: #fef3c7;
      color: #92400e;
    }
    .leg-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem 0.8rem;
      font-size: 0.78rem;
      color: #4b5563;
      margin-bottom: 0.3rem;
    }
    .bridges-summary {
      font-size: 0.78rem;
      color: #4b5563;
    }
    .bridges-summary strong {
      font-weight: 600;
    }
    footer {
      margin-top: 1.3rem;
      font-size: 0.78rem;
      color: var(--muted);
    }
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
      <p>Keep your drop order – RouteSafe AI checks each leg for low bridges using ORS + a UK bridge dataset.</p>
      <div class="version">Prototype v0.1 | Internal Use Only</div>
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
    <footer>Data source: OpenRouteService + internal UK low bridge dataset.</footer>
  </div>

  <script>
    const BACKEND_URL = "/api/route";

    const form = document.getElementById("route-form");
    const statusEl = document.getElementById("status");
    const legsContainer = document.getElementById("legs-container");
    const generateBtn = document.getElementById("generate-btn");

    function setStatus(msg, type = "info") {
      if (!msg) {
        statusEl.textContent = "";
        statusEl.className = "status";
        return;
      }
      statusEl.textContent = msg;
      statusEl.className =
        type === "error" ? "status status-error" : "status status-ok";
    }

    function renderLegs(legs) {
      legsContainer.innerHTML = "";
      if (!legs || !legs.length) {
        legsContainer.innerHTML =
          '<div class="hint">No legs returned from backend.</div>';
        return;
      }
      legs.forEach((leg, idx) => {
        const bridges = leg.low_bridges || [];
        const risky = bridges.length > 0;
        const wrapper = document.createElement("div");
        wrapper.className = "leg";
        const header = document.createElement("div");
        header.className = "leg-header";
        const title = document.createElement("div");
        title.className = "leg-title";
        title.textContent = `Leg ${idx + 1}: ${leg.from_postcode} → ${leg.to_postcode}`;
        const pill = document.createElement("div");
        pill.className = "pill " + (risky ? "pill-risk" : "pill-safe");
        pill.textContent = risky ? "LOW BRIDGE(S)" : "HGV SAFE";
        header.appendChild(title);
        header.appendChild(pill);
        const meta = document.createElement("div");
        meta.className = "leg-meta";
        meta.innerHTML = `
          <span>Distance: ${leg.distance_km} km</span>
          <span>Time: ${leg.duration_min} min</span>
          <span>Vehicle height: ${leg.vehicle_height_m} m</span>
        `;
        const bridgesSummary = document.createElement("div");
        bridgesSummary.className = "bridges-summary";
        if (!risky) {
          bridgesSummary.textContent = "No low bridges on this leg.";
        } else {
          const first = bridges[0];
          const name = first.name || "Bridge";
          const extra = bridges.length - 1;
          const extraTxt = extra > 0 ? ` (+${extra} more)` : "";
          bridgesSummary.innerHTML =
            `<strong>${bridges.length}</strong> low bridge(s). ` +
            `${name} at approx ${first.bridge_height_m} m${extraTxt}.`;
        }
        wrapper.appendChild(header);
        wrapper.appendChild(meta);
        wrapper.appendChild(bridgesSummary);
        legsContainer.appendChild(wrapper);
      });
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const depot = document.getElementById("depot").value.trim();
      const height = parseFloat(document.getElementById("height").value);
      const stops = document
        .getElementById("stops")
        .value.split("\\n")
        .map((x) => x.trim())
        .filter((x) => x.length > 0);

      if (!depot || stops.length === 0) {
        setStatus("Enter depot + at least one postcode.", "error");
        return;
      }

      if (!height || height <= 0) {
        setStatus("Vehicle height must be a positive number in metres.", "error");
        return;
      }

      setStatus("Contacting backend…");
      generateBtn.disabled = true;

      try {
        const resp = await fetch(BACKEND_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            depot_postcode: depot,
            vehicle_height_m: height,
            stops: stops,
          }),
        });

        const text = await resp.text();
        let data = null;
        try { data = JSON.parse(text); } catch {}

        if (!resp.ok) {
          const errMsg =
            (data && (data.detail || data.message)) ||
            `Status ${resp.status}`;
          throw new Error(errMsg);
        }

        renderLegs(data.legs);
        setStatus("Route generated successfully.");
      } catch (err) {
        console.error(err);
        setStatus("Backend error: " + (err.message || err), "error");
        legsContainer.innerHTML =
          '<div class="hint">No results – backend returned an error.</div>';
      } finally {
        generateBtn.disabled = false;
      }
    });
  </script>
</body>
</html>
"""

# -------------------------------------------------------------------
# Helpers: ORS geocoding + routing
# -------------------------------------------------------------------

def geocode_postcode(postcode: str) -> Tuple[float, float]:
    """Geocode a UK postcode using ORS. Returns (lat, lon)."""
    if not ORS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ORS_API_KEY is not configured on the server.",
        )

    text = postcode.strip().upper()
    if not text:
        raise HTTPException(
            status_code=400, detail="Empty postcode supplied for geocoding."
        )

    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text": text,
        "size": 1,
        "boundary.country": "GB",
    }

    try:
        resp = requests.get(url, params=params, timeout=20)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error calling ORS geocoding for '{text}': {exc}",
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=(
                f"ORS geocoding failed for '{text}' "
                f"(status {resp.status_code}): {resp.text[:300]}"
            ),
        )

    data = resp.json()
    features = data.get("features") or []
    if not features:
        raise HTTPException(
            status_code=400,
            detail=f"No geocoding result found for postcode '{text}'.",
        )

    coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
    lon, lat = coords[0], coords[1]
    return float(lat), float(lon)


def _extract_summary_from_ors(data: Dict[str, Any], raw_text: str) -> Dict[str, float]:
    """Normalise ORS JSON/GeoJSON into distance_km + duration_min."""
    summary: Dict[str, Any] | None = None
    try:
        if "routes" in data:
            summary = data["routes"][0]["summary"]
        elif "features" in data:
            summary = data["features"][0]["properties"]["summary"]
        else:
            raise KeyError("Neither 'routes' nor 'features' present")
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unexpected routing response from ORS: "
                f"{e} | payload: {raw_text[:300]}"
            ),
        )

    distance_km = float(summary["distance"]) / 1000.0
    duration_min = float(summary["duration"]) / 60.0

    return {
        "distance_km": round(distance_km, 2),
        "duration_min": round(duration_min, 1),
    }


def get_hgv_route_metrics(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
) -> Dict[str, float]:
    """Call ORS driving-hgv, falling back to driving-car if needed."""
    if not ORS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ORS_API_KEY is not configured on the server.",
        )

    def call_ors(profile: str):
        url = f"https://api.openrouteservice.org/v2/directions/{profile}"
        headers = {
            "Authorization": ORS_API_KEY,
            "Content-Type": "application/json",
        }
        body = {"coordinates": [[start_lon, start_lat], [end_lon, end_lat]]}
        resp = requests.post(url, json=body, headers=headers, timeout=25)
        return profile, resp

    last_error_txt: str | None = None

    for profile in ["driving-hgv", "driving-car"]:
        profile_used, resp = call_ors(profile)

        if resp.status_code != 200:
            last_error_txt = (
                f"{profile_used} status {resp.status_code}: {resp.text[:300]}"
            )
            continue

        raw_text = resp.text
        data: Dict[str, Any] = resp.json()
        return _extract_summary_from_ors(data, raw_text)

    raise HTTPException(
        status_code=502,
        detail=f"Routing failed via ORS: {last_error_txt or 'no response'}",
    )


# -------------------------------------------------------------------
# API endpoints
# -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return HTMLResponse(content=HTML_PAGE, status_code=200)


@app.get("/health")
def health():
    return {"ok": True, "service": "RouteSafe AI backend"}


@app.post("/api/route", response_model=RouteResponse)
def api_route(req: RouteRequest):
    """Main entry point for the frontend."""
    try:
        if not ORS_API_KEY:
            raise HTTPException(
                status_code=500,
                detail="ORS_API_KEY is not configured on the server.",
            )

        depot_pc = req.depot_postcode.strip().upper()
        stops_clean = [s.strip().upper() for s in req.stops if s.strip()]

        if not depot_pc:
            raise HTTPException(
                status_code=400, detail="Depot postcode must not be empty."
            )
        if not stops_clean:
            raise HTTPException(
                status_code=400,
                detail="At least one delivery postcode is required.",
            )
        if req.vehicle_height_m <= 0:
            raise HTTPException(
                status_code=400,
                detail="Vehicle height must be a positive number in metres.",
            )

        # Geocode all points
        points: List[Tuple[float, float]] = []
        postcodes: List[str] = []

        depot_lat, depot_lon = geocode_postcode(depot_pc)
        points.append((depot_lat, depot_lon))
        postcodes.append(depot_pc)

        for pc in stops_clean:
            lat, lon = geocode_postcode(pc)
            points.append((lat, lon))
            postcodes.append(pc)

        legs_out: List[Dict[str, Any]] = []

        for idx in range(len(points) - 1):
            start_lat, start_lon = points[idx]
            end_lat, end_lon = points[idx + 1]

            metrics = get_hgv_route_metrics(
                start_lon=start_lon,
                start_lat=start_lat,
                end_lon=end_lon,
                end_lat=end_lat,
            )

            # ---- LOW BRIDGE LOOKUP via BridgeEngine.check_leg ----
            result = bridge_engine.check_leg(
                start_lat=start_lat,
                start_lon=start_lon,
                end_lat=end_lat,
                end_lon=end_lon,
                vehicle_height_m=req.vehicle_height_m,
            )

            low_bridges: List[Dict[str, Any]] = []

            # For now we just expose the nearest bridge if any.
            if result.nearest_bridge is not None:
                low_bridges.append(
                    {
                        "name": None,
                        "bridge_height_m": float(result.nearest_bridge.height_m),
                        "distance_from_start_m": float(
                            result.nearest_distance_m or 0.0
                        ),
                        "lat": float(result.nearest_bridge.lat),
                        "lon": float(result.nearest_bridge.lon),
                    }
                )

            leg = {
                "from_postcode": postcodes[idx],
                "to_postcode": postcodes[idx + 1],
                "distance_km": metrics["distance_km"],
                "duration_min": metrics["duration_min"],
                "vehicle_height_m": req.vehicle_height_m,
                "low_bridges": low_bridges,
            }
            legs_out.append(leg)

        return {"legs": legs_out}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected server error: {e}",
        )