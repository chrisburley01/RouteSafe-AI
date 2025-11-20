// =============================
// CONFIG
// =============================

// Your FastAPI backend on Render
// Change this if your URL is different
const BACKEND_BASE = "https://routesafe-ai.onrender.com";

// Convenience: grab elements once
const form = document.getElementById("routeForm");
const depotInput = document.getElementById("depotPostcode");
const stopsInput = document.getElementById("stopsTextarea");   // one stop per line
const heightInput = document.getElementById("vehicleHeight");  // metres
const routeSummary = document.getElementById("routeSummary");
const routeLegs = document.getElementById("routeLegs");
const errorBox = document.getElementById("errorBox");
const debugBox = document.getElementById("debugBox");          // optional

// =============================
// Helpers
// =============================

function setLoading(isLoading) {
  const btn = document.getElementById("generateBtn");
  if (!btn) return;

  if (isLoading) {
    btn.disabled = true;
    btn.textContent = "Calculating...";
  } else {
    btn.disabled = false;
    btn.textContent = "Generate safe legs";
  }
}

function showError(message) {
  if (errorBox) {
    errorBox.textContent = message;
    errorBox.style.display = "block";
  } else {
    alert(message);
  }
}

function clearError() {
  if (errorBox) {
    errorBox.textContent = "";
    errorBox.style.display = "none";
  }
}

function logDebug(message, data = null) {
  console.log("[RouteSafe debug]", message, data || "");
  if (debugBox) {
    const line = document.createElement("div");
    line.textContent =
      `[${new Date().toLocaleTimeString()}] ${message}` +
      (data ? ` :: ${JSON.stringify(data).slice(0, 400)}` : "");
    debugBox.appendChild(line);
  }
}

function parseStops(raw) {
  return raw
    .split(/\r?\n|,/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

// =============================
// Rendering
// =============================

function renderResults(data, depotPostcode, stops) {
  routeLegs.innerHTML = "";

  const vehicleHeight = data.vehicle_height_m;

  // Summary line
  const totalLegs = data.legs.length;
  const totalText = `Route calculated • ${totalLegs} leg${
    totalLegs === 1 ? "" : "s"
  } • vehicle height ${vehicleHeight.toFixed(2)} m`;

  if (routeSummary) {
    routeSummary.textContent = totalText;
  }

  // Build each leg card
  data.legs.forEach((leg, index) => {
    const card = document.createElement("div");
    card.className = "route-leg-card";

    const legTitle = document.createElement("h3");
    const fromLabel = index === 0 ? depotPostcode : stops[index - 1];
    const toLabel = stops[index];
    legTitle.textContent = `Leg ${index + 1}: ${fromLabel} → ${toLabel}`;
    card.appendChild(legTitle);

    // Warnings section
    const warnings = leg.warnings || [];
    const warnP = document.createElement("p");

    if (warnings.length === 0) {
      warnP.textContent = "No low bridges detected on this leg.";
      warnP.className = "safe-text";
    } else {
      warnP.innerHTML = `<strong>Warning:</strong> ${warnings.length} possible low bridge(s) near this route.`;
      warnP.className = "warn-text";

      const list = document.createElement("ul");
      warnings.forEach((w) => {
        const li = document.createElement("li");
        li.textContent = `Bridge ${w.bridge_height_m.toFixed(
          2
        )} m at approx ${w.bridge_lat.toFixed(5)}, ${w.bridge_lon.toFixed(
          5
        )} (≈${w.distance_km.toFixed(2)} km from path)`;
        list.appendChild(li);
      });
      card.appendChild(list);
    }
    card.appendChild(warnP);

    // Google Maps link
    if (leg.maps_link) {
      const link = document.createElement("a");
      link.href = leg.maps_link;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open this leg in Google Maps";
      link.className = "maps-link";
      card.appendChild(link);
    }

    routeLegs.appendChild(card);
  });
}

// =============================
// Form handler
// =============================

async function handleSubmit(event) {
  event.preventDefault();
  clearError();
  logDebug("Submitting route form");

  const depotPostcode = depotInput.value.trim();
  const rawStops = stopsInput.value.trim();
  const vehicleHeight = parseFloat(heightInput.value);

  if (!depotPostcode) {
    showError("Please enter a depot postcode.");
    return;
  }

  const stops = parseStops(rawStops);
  if (stops.length === 0) {
    showError("Please enter at least one stop postcode.");
    return;
  }

  if (!vehicleHeight || vehicleHeight <= 0) {
    showError("Please enter a valid vehicle height in metres.");
    return;
  }

  const payload = {
    start: depotPostcode,
    stops: stops,
    vehicle_height_m: vehicleHeight,
  };

  logDebug("Payload to backend", payload);

  setLoading(true);

  try {
    const response = await fetch(`${BACKEND_BASE}/route`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const text = await response.text();
      logDebug("Backend error response", text);
      throw new Error(
        `Backend error (${response.status}): ${
          text || "Unexpected problem contacting RouteSafe backend."
        }`
      );
    }

    const data = await response.json();
    logDebug("Backend JSON received", data);

    renderResults(data, depotPostcode, stops);
  } catch (err) {
    console.error(err);
    showError(err.message || "Something went wrong generating the route.");
  } finally {
    setLoading(false);
  }
}

// =============================
// Wire up
// =============================

if (form) {
  form.addEventListener("submit", handleSubmit);
  logDebug("routeForm listener attached");
} else {
  console.warn(
    "RouteSafe: No form with id 'routeForm' found – check your HTML IDs."
  );
}
