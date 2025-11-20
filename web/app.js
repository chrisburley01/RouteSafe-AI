const BACKEND_URL = "https://routesafe-ai.onrender.com/api/route"; // change if needed

const depotInput = document.getElementById("depot-postcode");
const stopsInput = document.getElementById("stops");
const heightInput = document.getElementById("vehicle-height");
const generateBtn = document.getElementById("generate-btn");
const errorBox = document.getElementById("error-box");
const legsContainer = document.getElementById("route-legs");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function normalisePostcode(pc) {
  return pc.trim().toUpperCase();
}

generateBtn.addEventListener("click", async () => {
  clearError();

  const depot = normalisePostcode(depotInput.value);
  const rawStops = stopsInput.value
    .split("\n")
    .map((s) => normalisePostcode(s))
    .filter((s) => s.length > 0);
  const height = parseFloat(heightInput.value);

  if (!depot) {
    showError("Please enter the depot postcode.");
    return;
  }
  if (rawStops.length === 0) {
    showError("Please enter at least one delivery postcode.");
    return;
  }
  if (!height || height <= 0) {
    showError("Please enter a valid vehicle height in metres.");
    return;
  }

  const payload = {
    depot_postcode: depot,
    stops: rawStops,
    vehicle_height_m: height,
  };

  generateBtn.disabled = true;
  generateBtn.textContent = "Checking bridges…";

  try {
    const resp = await fetch(BACKEND_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const data = await resp.json().catch(() => null);

    if (!resp.ok) {
      const detail =
        (data && (data.detail || data.message)) ||
        `HTTP ${resp.status} from backend`;
      showError(`Backend error: ${detail}`);
      return;
    }

    renderLegs(data);
  } catch (err) {
    console.error(err);
    showError("Failed to contact backend. Please try again in a moment.");
  } finally {
    generateBtn.disabled = false;
    generateBtn.textContent = "Generate safe legs";
  }
});

function renderLegs(response) {
  const legs = response.legs || [];

  if (!Array.isArray(legs) || legs.length === 0) {
    legsContainer.innerHTML =
      '<p class="placeholder">No legs returned from backend.</p>';
    return;
  }

  legsContainer.innerHTML = "";

  legs.forEach((leg) => {
    const card = document.createElement("div");
    card.className = "leg-card";

    const topline = document.createElement("div");
    topline.className = "leg-topline";

    const title = document.createElement("div");
    title.className = "leg-title";
    title.textContent = `${leg.from_postcode} → ${leg.to_postcode}`;

    const metrics = document.createElement("div");
    metrics.className = "leg-metrics";
    metrics.textContent = `${leg.distance_km} km · approx ${leg.duration_min} mins · vehicle ${leg.vehicle_height_m} m`;

    topline.appendChild(title);
    topline.appendChild(metrics);

    const hasWarnings =
      Array.isArray(leg.low_bridges) && leg.low_bridges.length > 0;

    const badge = document.createElement("span");
    badge.className = hasWarnings ? "badge-warning" : "badge-ok";
    badge.textContent = hasWarnings
      ? `${leg.low_bridges.length} possible low bridge(s)`
      : "No low bridges detected near this leg";

    const bridgeList = document.createElement("ul");
    bridgeList.className = "bridge-list";

    if (hasWarnings) {
      leg.low_bridges.forEach((b) => {
        const li = document.createElement("li");
        const namePart = b.name ? `${b.name} – ` : "";
        li.textContent = `${namePart}${b.bridge_height_m} m bridge, approx ${
          Math.round(b.distance_from_start_m) / 10 / 100
        } km from start`;
        bridgeList.appendChild(li);
      });
    }

    card.appendChild(topline);
    card.appendChild(badge);
    if (hasWarnings) {
      card.appendChild(bridgeList);
    }

    legsContainer.appendChild(card);
  });
}
