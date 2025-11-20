// app.js – RouteSafe AI frontend

const API_BASE_URL = "https://routesafe-ai.onrender.com"; // your Render backend

document.addEventListener("DOMContentLoaded", () => {
  console.log("RouteSafe AI frontend loaded");

  const form = document.getElementById("route-form");
  const statusEl =
    document.getElementById("route-status") ||
    document.getElementById("status-message");
  const resultsEl =
    document.getElementById("route-results") ||
    document.getElementById("route-legs");

  if (!form) {
    console.error("route-form not found in DOM");
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault(); // <- stops the page reload

    clearStatus();
    clearResults();

    try {
      // 🔧 Adjust these IDs if yours are different
      const depotInput =
        document.getElementById("depot-postcode") ||
        document.getElementById("depotPostcode");
      const stopsInput =
        document.getElementById("stops-input") ||
        document.getElementById("stopsText");
      const heightInput =
        document.getElementById("vehicle-height") ||
        document.getElementById("vehicleHeight");

      if (!depotInput || !stopsInput || !heightInput) {
        throw new Error(
          "Form wiring error: check input IDs in app.js match your HTML."
        );
      }

      const depotPostcode = depotInput.value.trim();
      const stopsRaw = stopsInput.value
        .split("\n")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      const vehicleHeightStr = heightInput.value.trim();

      if (!depotPostcode) {
        throw new Error("Please enter a depot postcode.");
      }
      if (stopsRaw.length === 0) {
        throw new Error("Please enter at least one stop postcode.");
      }
      if (!vehicleHeightStr) {
        throw new Error("Please enter the vehicle height in metres.");
      }

      const vehicleHeight = parseFloat(vehicleHeightStr);
      if (Number.isNaN(vehicleHeight) || vehicleHeight <= 0) {
        throw new Error("Vehicle height must be a positive number in metres.");
      }

      setStatus("Calculating safe route and checking bridges…", "info");

      const payload = {
        depot_postcode: depotPostcode,
        stops: stopsRaw,
        vehicle_height_m: vehicleHeight,
      };

      console.log("Sending request to backend:", payload);

      const response = await fetch(`${API_BASE_URL}/plan_route`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const text = await response.text();
        console.error("Backend error:", response.status, text);
        throw new Error(
          `Backend error ${response.status}: ${
            text || "Unable to calculate route."
          }`
        );
      }

      const data = await response.json();
      console.log("Backend response:", data);

      renderResults(data);
      setStatus(
        "Route calculated. Distances/times rough until HGV router is plugged in, but bridge checks are live.",
        "success"
      );
    } catch (err) {
      console.error(err);
      setStatus(err.message || "Something went wrong.", "error");
    }
  });

  // --- helpers ---

  function setStatus(message, level) {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.remove("status-info", "status-success", "status-error");
    if (level === "success") statusEl.classList.add("status-success");
    else if (level === "error") statusEl.classList.add("status-error");
    else statusEl.classList.add("status-info");
  }

  function clearStatus() {
    if (!statusEl) return;
    statusEl.textContent = "";
    statusEl.classList.remove("status-info", "status-success", "status-error");
  }

  function clearResults() {
    if (!resultsEl) return;
    resultsEl.innerHTML = "";
  }

  function renderResults(data) {
    if (!resultsEl) return;

    const legs = data.legs || [];
    const totalKm = data.total_km ?? null;
    const totalMinutes = data.total_minutes ?? null;

    let html = "";

    if (totalKm !== null || totalMinutes !== null) {
      html += `
        <div class="route-summary">
          <p><strong>Total:</strong> 
            ${totalKm !== null ? `${totalKm.toFixed(1)} km` : ""} 
            ${totalMinutes !== null ? `· approx ${Math.round(totalMinutes)} mins` : ""}
          </p>
        </div>
      `;
    }

    if (legs.length === 0) {
      html += `<p>No legs returned from the backend.</p>`;
      resultsEl.innerHTML = html;
      return;
    }

    html += `<div class="route-legs-list">`;

    for (const leg of legs) {
      const label = leg.label || `${leg.from} → ${leg.to}`;
      const km = leg.distance_km;
      const mins = leg.duration_minutes;
      const mapsUrl = leg.google_maps_url;
      const warnings = leg.bridge_warnings || [];

      html += `<div class="route-leg-card">`;
      html += `<div class="route-leg-header"><strong>${label}</strong></div>`;
      html += `<div class="route-leg-meta">`;

      if (typeof km === "number") {
        html += `<span>${km.toFixed(1)} km</span>`;
      }
      if (typeof mins === "number") {
        html += `<span>· approx ${Math.round(mins)} mins</span>`;
      }

      html += `</div>`;

      if (mapsUrl) {
        html += `<div class="route-leg-link"><a href="${mapsUrl}" target="_blank" rel="noopener noreferrer">Open this leg in Google Maps</a></div>`;
      }

      if (warnings.length > 0) {
        html += `<ul class="bridge-warnings">`;
        for (const w of warnings) {
          html += `<li>⚠️ ${w}</li>`;
        }
        html += `</ul>`;
      } else {
        html += `<p class="no-warnings">✅ No low bridges detected on this leg based on Network Rail data.</p>`;
      }

      html += `</div>`;
    }

    html += `</div>`;
    resultsEl.innerHTML = html;
  }
});
