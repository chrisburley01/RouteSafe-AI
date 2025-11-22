// RouteSafe-AI web v5 – multi-leg planner

const API_BASE = "https://routesafe-ai.onrender.com";

const form = document.getElementById("routeForm");
const depotInput = document.getElementById("depotPostcode");
const deliveriesInput = document.getElementById("deliveryPostcodes");
const heightInput = document.getElementById("vehicleHeight");
const avoidInput = document.getElementById("avoidLowBridges");
const statusEl = document.getElementById("statusMessage");
const resultsCard = document.getElementById("resultsCard");
const legsContainer = document.getElementById("legsContainer");
const generateBtn = document.getElementById("generateBtn");

// Optional: a sensible default depot if empty
if (!depotInput.value.trim()) {
  depotInput.value = "LS27 0BN";
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  await generateLegs();
});

async function generateLegs() {
  const depot = depotInput.value.trim();
  const heightStr = heightInput.value.trim();
  const avoid = !!avoidInput.checked;

  const deliveries = deliveriesInput.value
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  if (!depot || deliveries.length === 0 || !heightStr) {
    showStatus(
      "Please enter depot, at least one delivery postcode, and vehicle height.",
      "error"
    );
    return;
  }

  const vehicleHeight = parseFloat(heightStr);
  if (Number.isNaN(vehicleHeight) || vehicleHeight <= 0) {
    showStatus("Vehicle height must be a positive number.", "error");
    return;
  }

  generateBtn.disabled = true;
  showStatus("Generating routes and checking bridges…", "info");
  legsContainer.innerHTML = "";
  resultsCard.style.display = "none";

  try {
    const allLegs = [];

    let currentStart = depot;
    for (let i = 0; i < deliveries.length; i++) {
      const end = deliveries[i];

      const legIndex = i + 1;
      const legResult = await fetchRouteLeg(
        legIndex,
        currentStart,
        end,
        vehicleHeight,
        avoid
      );

      allLegs.push(legResult);
      currentStart = end;
    }

    renderLegs(allLegs);
    resultsCard.style.display = "block";
    showStatus("Route generated successfully.", "success");
  } catch (err) {
    console.error(err);
    showStatus(
      `Error generating route: ${
        err?.message || "Unexpected error from RouteSafe-AI."
      }`,
      "error"
    );
  } finally {
    generateBtn.disabled = false;
  }
}

async function fetchRouteLeg(legNumber, start, end, vehicleHeight, avoidLow) {
  const payload = {
    start,
    end,
    vehicle_height_m: vehicleHeight,
    avoid_low_bridges: avoidLow,
  };

  const res = await fetch(`${API_BASE}/api/route`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      `RouteSafe-AI error ${res.status}: ${text || res.statusText}`
    );
  }

  const data = await res.json();
  return {
    legNumber,
    start_used: data.start_used,
    end_used: data.end_used,
    distance_m: data.distance_m ?? 0,
    duration_s: data.duration_s ?? 0,
    bridge_risk: data.bridge_risk ?? {
      has_conflict: false,
      near_height_limit: false,
      nearest_bridge_height_m: null,
      nearest_bridge_distance_m: null,
      note: null,
    },
  };
}

function renderLegs(legs) {
  legsContainer.innerHTML = "";

  legs.forEach((leg) => {
    const distanceKm = (leg.distance_m / 1000).toFixed(1);
    const minutes = Math.round(leg.duration_s / 60);
    const risk = leg.bridge_risk || {};
    const hasConflict = !!risk.has_conflict;
    const nearLimit = !!risk.near_height_limit;

    const card = document.createElement("div");
    card.className = "leg-card";

    const header = document.createElement("div");
    header.className = "leg-header";

    const title = document.createElement("div");
    title.className = "leg-title";
    title.textContent = `Leg ${leg.legNumber}: ${leg.start_used} \u2192 ${leg.end_used}`;

    const badge = document.createElement("span");
    if (hasConflict) {
      badge.className = "badge-danger";
      badge.textContent = "Low bridge risk";
    } else {
      badge.className = "badge-safe";
      badge.textContent = nearLimit ? "Near height limit" : "HGV safe";
    }

    header.appendChild(title);
    header.appendChild(badge);

    const meta = document.createElement("div");
    meta.className = "leg-meta";
    meta.textContent = `Distance: ${distanceKm} km · Time: ${minutes} min`;

    const body = document.createElement("div");
    body.className = "leg-body";

    if (hasConflict) {
      const wrapper = document.createElement("div");
      wrapper.className = "leg-warning";

      const emoji = document.createElement("div");
      emoji.className = "leg-warning-emoji";
      emoji.textContent = "⚠️";

      const text = document.createElement("div");
      text.innerHTML =
        "Low bridge on this leg. Route not HGV safe at current height. " +
        "Direct route only – preview in Google Maps and use with caution.";

      wrapper.appendChild(emoji);
      wrapper.appendChild(text);
      body.appendChild(wrapper);
    } else if (nearLimit) {
      body.textContent =
        "No bridge conflicts at this height, but one or more structures are close to your running height. Drive with extra care.";
    } else {
      body.textContent = "No low-bridge conflicts detected on this leg.";
    }

    const mapsBtn = document.createElement("button");
    mapsBtn.className = "maps-btn";
    mapsBtn.textContent = "Open in Google Maps (preview route)";
    mapsBtn.addEventListener("click", () => {
      const url = buildGoogleMapsUrl(leg.start_used, leg.end_used);
      window.open(url, "_blank");
    });

    card.appendChild(header);
    card.appendChild(meta);
    card.appendChild(body);
    card.appendChild(mapsBtn);

    legsContainer.appendChild(card);
  });
}

function buildGoogleMapsUrl(start, end) {
  const origin = encodeURIComponent(start);
  const destination = encodeURIComponent(end);
  return `https://www.google.com/maps/dir/?api=1&origin=${origin}&destination=${destination}`;
}

function showStatus(message, type) {
  statusEl.textContent = message;
  statusEl.classList.remove("success", "error");

  if (type === "success") statusEl.classList.add("success");
  else if (type === "error") statusEl.classList.add("error");
}