// ============================
// RouteSafe AI – app.js
// ============================

// LIVE backend URL (Render)
const API_BASE_URL = "https://routesafe-ai.onrender.com";

// ----- DOM references -----
const form = document.getElementById("route-form");
const statusEl = document.getElementById("status");
const resultsCard = document.getElementById("results-card");
const legsListEl = document.getElementById("legs-list");
const summaryEl = document.getElementById("summary");
const planPhotoInput = document.getElementById("plan-photo");
const stopsTextarea = document.getElementById("stops");
const depotInput = document.getElementById("depot-postcode");
const heightInput = document.getElementById("vehicle-height");

// ---------- helpers ---------- //

function setStatus(message, type = "info") {
  statusEl.textContent = message || "";
  statusEl.classList.remove("rs-info", "rs-error", "rs-success");

  if (type === "error") {
    statusEl.classList.add("rs-error");
  } else if (type === "success") {
    statusEl.classList.add("rs-success");
  } else {
    statusEl.classList.add("rs-info");
  }
}

function clearResults() {
  resultsCard.classList.add("hidden");
  resultsCard.classList.remove("rs-safe", "rs-warning", "rs-unsafe");
  legsListEl.innerHTML = "";
  summaryEl.textContent = "";
}

function normaliseStops(rawText) {
  return rawText
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

// Decide overall severity from legs
function getRouteSeverity(legs) {
  let hasConflict = false;
  let nearLimit = false;

  (legs || []).forEach((leg) => {
    if (leg.has_conflict || leg.safe === false) {
      hasConflict = true;
    } else if (leg.near_height_limit) {
      nearLimit = true;
    }
  });

  if (hasConflict) return "unsafe";
  if (nearLimit) return "warning";
  return "safe";
}

// Render the plan that comes back from the API
function renderPlan(data) {
  if (!data) {
    clearResults();
    setStatus("No data returned from server.", "error");
    return;
  }

  const legs = data.legs || [];
  const vehicleHeight = data.vehicle_height_m;
  const totalKm = data.total_distance_km;
  const totalMin = data.total_duration_min;

  // Summary line
  let summaryParts = [];
  if (typeof totalKm === "number") {
    summaryParts.push(`Total: ${totalKm.toFixed(1)} km`);
  }
  if (typeof totalMin === "number") {
    summaryParts.push(`approx ${totalMin.toFixed(0)} mins`);
  }
  if (typeof vehicleHeight === "number") {
    summaryParts.push(`vehicle height ${vehicleHeight.toFixed(2)} m`);
  }

  summaryEl.textContent = summaryParts.join(" • ");

  // Clear any old legs
  legsListEl.innerHTML = "";

  // Build each leg
  legs.forEach((leg, index) => {
    const item = document.createElement("div");
    item.className = "leg-item";

    const fromLabel = leg.from_ || leg.from || `Leg ${index + 1} start`;
    const toLabel = leg.to || `Leg ${index + 1} end`;

    // Determine leg safety
    const bridge = leg.bridge || null;
    const hasConflict =
      leg.has_conflict ||
      leg.safe === false ||
      (bridge && typeof bridge.clearance_m === "number" && bridge.clearance_m <= 0);

    const nearLimit =
      !hasConflict &&
      (leg.near_height_limit ||
        (bridge &&
          typeof bridge.clearance_m === "number" &&
          bridge.clearance_m > 0 &&
          bridge.clearance_m <= 0.25)); // 25 cm buffer

    let statusText = "";
    let statusClass = "";

    if (hasConflict) {
      const h =
        bridge && typeof bridge.height_m === "number"
          ? `${bridge.height_m.toFixed(2)} m`
          : "unknown height";
      const clr =
        bridge && typeof bridge.clearance_m === "number"
          ? `${bridge.clearance_m.toFixed(2)} m clearance`
          : "";
      statusText = `LOW BRIDGE – UNSAFE ❌  (bridge ${h}${clr ? ", " + clr : ""})`;
      statusClass = "leg-status-unsafe";
    } else if (nearLimit) {
      const h =
        bridge && typeof bridge.height_m === "number"
          ? `${bridge.height_m.toFixed(2)} m`
          : "near your vehicle height";
      statusText = `Near height limit ⚠️  (bridge ${h})`;
      statusClass = "leg-status-warning";
    } else {
      statusText = "No low bridges detected ✓";
      statusClass = "leg-status-safe";
    }

    // Google Maps link (we just use the labels; Google is good at guessing)
    const gmUrl =
      "https://www.google.com/maps/dir/" +
      encodeURIComponent(fromLabel) +
      "/" +
      encodeURIComponent(toLabel);

    item.innerHTML = `
      <div class="leg-header">
        <div class="leg-title">
          <strong>${fromLabel}</strong> → <strong>${toLabel}</strong>
        </div>
        <div class="leg-meta">
          ${
            typeof leg.distance_km === "number"
              ? `${leg.distance_km.toFixed(1)} km`
              : ""
          }
          ${
            typeof leg.duration_min === "number"
              ? ` · approx ${leg.duration_min.toFixed(0)} mins`
              : ""
          }
        </div>
      </div>
      <div class="leg-status ${statusClass}">
        ${statusText}
      </div>
      <div class="leg-links">
        <a href="${gmUrl}" target="_blank" rel="noopener noreferrer">
          Open this leg in Google Maps
        </a>
      </div>
    `;

    legsListEl.appendChild(item);
  });

  // Overall route badge on the card
  const severity = getRouteSeverity(legs);
  resultsCard.classList.remove("hidden", "rs-safe", "rs-warning", "rs-unsafe");

  if (severity === "unsafe") {
    resultsCard.classList.add("rs-unsafe");
    setStatus(
      "Route calculated, but at least one leg passes a LOW BRIDGE. Check red cards carefully.",
      "error"
    );
  } else if (severity === "warning") {
    resultsCard.classList.add("rs-warning");
    setStatus(
      "Route calculated. Some legs are close to your height limit – check amber cards.",
      "info"
    );
  } else {
    resultsCard.classList.add("rs-safe");
    setStatus(
      "Route calculated. Distances/times are rough until an HGV router is used, but bridge checks are live.",
      "success"
    );
  }
}

// ---------- form submit handler ---------- //

form.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  clearResults();

  const depot = depotInput.value.trim();
  const stops = normaliseStops(stopsTextarea.value || "");
  const vehicleHeightStr = (heightInput.value || "").trim();
  const vehicleHeight = vehicleHeightStr ? parseFloat(vehicleHeightStr) : null;

  if (!depot) {
    setStatus("Please enter a depot postcode.", "error");
    return;
  }
  if (!stops.length) {
    setStatus("Please enter at least one stop postcode.", "error");
    return;
  }
  if (!vehicleHeight || isNaN(vehicleHeight)) {
    setStatus("Please enter your vehicle height in metres.", "error");
    return;
  }

  // Currently we only use typed data; photo upload BETA can be wired later
  const payload = {
    depot_postcode: depot,
    stops: stops,
    vehicle_height_m: vehicleHeight,
  };

  setStatus("Calculating bridge-safe legs…", "info");

  try {
    const response = await fetch(`${API_BASE_URL}/plan`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const text = await response.text();
      console.error("Backend error:", response.status, text);
      setStatus(
        `Server error (${response.status}). Please try again in a moment.`,
        "error"
      );
      return;
    }

    const data = await response.json();
    renderPlan(data);
  } catch (err) {
    console.error("Request failed:", err);
    setStatus(
      "Could not reach the RouteSafe server. Check your signal and try again.",
      "error"
    );
  }
});

// ---------- initial ---------- //

setStatus("Enter your route and vehicle height, then tap “Generate safe legs”.", "info");
clearResults();