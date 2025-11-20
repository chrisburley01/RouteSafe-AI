// Point the web frontend at Render backend
const BACKEND_URL = "https://routesafe-ai.onrender.com/api/route";

const form = document.getElementById("route-form");
const statusEl = document.getElementById("status");
const legsContainer = document.getElementById("legs-container");
const generateBtn = document.getElementById("generate-btn");

// Leaflet map globals
let map = null;
let routeLayer = null;
let bridgeLayer = null;

function ensureMap() {
  if (!window.L) return;
  if (!map) {
    map = L.map("map");
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    map.setView([53.8, -1.5], 6); // UK-ish
  }
  if (!bridgeLayer) {
    bridgeLayer = L.layerGroup().addTo(map);
  }
}

function updateMap(legs) {
  ensureMap();
  if (!map) return;

  // Clear previous
  if (routeLayer) {
    routeLayer.remove();
    routeLayer = null;
  }
  if (bridgeLayer) {
    bridgeLayer.clearLayers();
  }

  const allLatLngs = [];

  if (!legs || !legs.length) return;

  legs.forEach((leg) => {
    const start = [leg.start_lat, leg.start_lon];
    const end = [leg.end_lat, leg.end_lon];

    allLatLngs.push(start);
    allLatLngs.push(end);

    (leg.low_bridges || []).forEach((b) => {
      const m = L.circleMarker([b.lat, b.lon], {
        radius: 5,
      });
      m.bindPopup(`Low bridge ~${b.bridge_height_m.toFixed(2)} m`);
      bridgeLayer.addLayer(m);
    });
  });

  if (!allLatLngs.length) return;

  routeLayer = L.polyline(allLatLngs, { weight: 4 });
  routeLayer.addTo(map);
  map.fitBounds(routeLayer.getBounds(), { padding: [20, 20] });
}

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
    title.textContent = `Leg ${idx + 1}: ${leg.from_postcode} → ${
      leg.to_postcode
    }`;

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
      const extra = bridges.length - 1;
      const extraTxt = extra > 0 ? ` (+${extra} more)` : "";
      bridgesSummary.innerHTML =
        `<strong>${bridges.length}</strong> low bridge(s). ` +
        `Bridge at approx ${first.bridge_height_m} m${extraTxt}.`;
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
    .value.split("\n")
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
    try {
      data = JSON.parse(text);
    } catch {}

    if (!resp.ok) {
      const errMsg =
        (data && (data.detail || data.message)) || `Status ${resp.status}`;
      throw new Error(errMsg);
    }

    renderLegs(data.legs);
    updateMap(data.legs);
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

// initialise empty map
document.addEventListener("DOMContentLoaded", ensureMap);