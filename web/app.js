// ====== CONFIG ======
const BACKEND_BASE = "https://routesafe-ai.onrender.com";

// Helper: turn textarea into clean list of postcodes
function parsePostcodes(raw) {
  return raw
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

// Try /api/route first, fall back to /route if 404
async function callRouteEndpoint(payload) {
  const tryPaths = ["/api/route", "/route"];

  for (const path of tryPaths) {
    const url = `${BACKEND_BASE}${path}`;
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    if (res.status === 404) {
      // Try next path
      continue;
    }

    // Any other status: return as-is (may still be an error)
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(
        `Backend ${res.status}: ${
          data.detail || data.error || JSON.stringify(data)
        }`
      );
    }
    return data;
  }

  throw new Error("Backend route not found at /api/route or /route");
}

function renderLegs(container, result) {
  container.innerHTML = "";

  if (!result || !Array.isArray(result.legs) || result.legs.length === 0) {
    const p = document.createElement("p");
    p.textContent = "No legs returned from backend.";
    container.appendChild(p);
    return;
  }

  const summary = document.createElement("p");
  summary.className = "summary";
  const totalKm =
    typeof result.total_distance_km === "number"
      ? result.total_distance_km.toFixed(1)
      : "–";
  const totalMins =
    typeof result.total_time_mins === "number"
      ? result.total_time_mins.toFixed(0)
      : "–";

  summary.textContent = `Total: ${totalKm} km · approx ${totalMins} mins · vehicle height ${result.vehicle_height_m} m`;
  container.appendChild(summary);

  result.legs.forEach((leg, idx) => {
    const card = document.createElement("div");
    card.className = "leg-card";

    const title = document.createElement("div");
    title.className = "leg-title";
    title.textContent = `Leg ${idx + 1}: ${leg.from} → ${leg.to}`;
    card.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "leg-meta";
    const km = typeof leg.distance_km === "number"
      ? `${leg.distance_km.toFixed(1)} km`
      : "–";
    const mins = typeof leg.time_mins === "number"
      ? `${leg.time_mins.toFixed(0)} mins`
      : "–";
    meta.textContent = `${km} · approx ${mins}`;
    card.appendChild(meta);

    if (Array.isArray(leg.low_bridges) && leg.low_bridges.length > 0) {
      const warn = document.createElement("div");
      warn.className = "leg-warning";
      warn.textContent = `⚠️ Low bridges on shortest path – rerouted to avoid: ${leg.low_bridges.length}`;
      card.appendChild(warn);
    } else {
      const ok = document.createElement("div");
      ok.className = "leg-ok";
      ok.textContent = "✅ No low bridges on this leg (based on current data)";
      card.appendChild(ok);
    }

    if (leg.google_maps_url) {
      const link = document.createElement("a");
      link.href = leg.google_maps_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.className = "leg-link";
      link.textContent = "Open this leg in Google Maps";
      card.appendChild(link);
    }

    container.appendChild(card);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const depotInput = document.getElementById("depot");
  const stopsInput = document.getElementById("stops");
  const heightInput = document.getElementById("vehicleHeight");
  const generateBtn = document.getElementById("generateBtn");
  const statusEl = document.getElementById("status");
  const legsContainer = document.getElementById("legsContainer");

  generateBtn.addEventListener("click", async () => {
    statusEl.textContent = "";
    statusEl.className = "status";
    legsContainer.innerHTML = "";

    const depot = depotInput.value.trim();
    const stops = parsePostcodes(stopsInput.value);
    const height = parseFloat(heightInput.value);

    if (!depot) {
      statusEl.textContent = "Please enter a depot postcode.";
      statusEl.classList.add("status-error");
      return;
    }
    if (stops.length === 0) {
      statusEl.textContent = "Please enter at least one delivery postcode.";
      statusEl.classList.add("status-error");
      return;
    }
    if (!height || Number.isNaN(height)) {
      statusEl.textContent = "Please enter a valid vehicle height in metres.";
      statusEl.classList.add("status-error");
      return;
    }

    const allPostcodes = [depot, ...stops];

    const payload = {
      depot_postcode: depot,
      postcodes: allPostcodes,
      vehicle_height_m: height
    };

    generateBtn.disabled = true;
    generateBtn.textContent = "Calculating...";
    statusEl.textContent = "Contacting RouteSafe AI backend…";
    statusEl.classList.remove("status-error");
    statusEl.classList.add("status-info");

    try {
      const result = await callRouteEndpoint(payload);
      statusEl.textContent = "Route calculated. Distances/times rough until HGV router is plugged in, but bridge checks are live.";
      statusEl.classList.remove("status-error");
      statusEl.classList.add("status-success");

      renderLegs(legsContainer, result);
    } catch (err) {
      console.error(err);
      statusEl.textContent = `Backend error: ${err.message}`;
      statusEl.classList.remove("status-info", "status-success");
      statusEl.classList.add("status-error");
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = "Generate safe legs";
    }
  });
});
