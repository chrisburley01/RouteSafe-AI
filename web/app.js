// web/app.js
// RouteSafe AI frontend
// Version: 0.5.0  (single route + guided alternative via Google Maps)

document.addEventListener("DOMContentLoaded", () => {
  // Backend base URL (Render backend)
  const API_BASE = "https://routesafe-ai.onrender.com";

  // Default origin (depot)
  const DEFAULT_ORIGIN = "LS270BN";

  const vehicleHeightInput =
    document.getElementById("vehicleHeight") ||
    document.querySelector("[data-role='vehicle-height']");
  const deliveryPostcodesInput =
    document.getElementById("deliveryPostcodes") ||
    document.querySelector("[data-role='delivery-postcodes']");
  const originPostcodeInput = document.getElementById("originPostcode"); // optional
  const generateBtn =
    document.getElementById("generateRouteBtn") ||
    document.querySelector("[data-role='generate-route']");
  const statusEl =
    document.getElementById("routeStatus") ||
    document.querySelector("[data-role='route-status']");
  const legsContainer =
    document.getElementById("routeLegsContainer") ||
    document.getElementById("route-legs") ||
    document.querySelector("[data-role='route-legs']");

  async function generateRoute() {
    const vehicleHeight = parseFloat(vehicleHeightInput?.value);
    const originPostcode =
      (originPostcodeInput && originPostcodeInput.value.trim()) ||
      DEFAULT_ORIGIN;
    const deliveryLines = (deliveryPostcodesInput?.value || "")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);

    if (!vehicleHeight || !originPostcode || deliveryLines.length === 0) {
      if (statusEl) {
        statusEl.textContent =
          "Please enter height and at least one delivery postcode.";
        statusEl.style.color = "#c0392b";
      }
      return;
    }

    if (statusEl) {
      statusEl.textContent = "Checking route for low bridges...";
      statusEl.style.color = "#6b7280";
    }
    if (legsContainer) legsContainer.innerHTML = "";
    if (generateBtn) generateBtn.disabled = true;

    try {
      const payload = {
        vehicleHeight: vehicleHeight,
        originPostcode: originPostcode,
        deliveryPostcodes: deliveryLines,
      };

      console.log("Sending payload", payload);

      const res = await fetch(API_BASE + "/api/route", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const txt = await res.text();
        console.error("Backend error response:", txt);
        throw new Error("Server error " + res.status + ": " + txt);
      }

      const data = await res.json();
      console.log("API response", data);
      renderLegs(data.legs || []);

      const anyLegs = data.legs && data.legs.length > 0;

      if (statusEl) {
        if (anyLegs) {
          statusEl.textContent = "Route generated successfully.";
          statusEl.style.color = "#1c7c3c";
        } else {
          statusEl.textContent =
            "No legs returned – please check your inputs and try again.";
          statusEl.style.color = "#c0392b";
        }
      }
    } catch (err) {
      console.error(err);
      if (statusEl) {
        statusEl.textContent =
          "There was a problem generating your route. Please try again.";
        statusEl.style.color = "#c0392b";
      }
    } finally {
      if (generateBtn) generateBtn.disabled = false;
    }
  }

  function renderLegs(legs) {
    if (!legsContainer) return;
    legsContainer.innerHTML = "";

    if (!legs || legs.length === 0) {
      legsContainer.innerHTML = "<p>No legs generated yet.</p>";
      return;
    }

    legs.forEach((leg) => {
      const card = document.createElement("div");
      card.className = "route-leg-card";

      const headerRow = document.createElement("div");
      headerRow.className = "route-leg-header-row";

      const title = document.createElement("h3");
      title.className = "route-leg-title";
      title.textContent = `Leg ${leg.index}: ${leg.start_postcode} → ${leg.end_postcode}`;

      const badge = document.createElement("span");
      badge.className = "route-leg-badge";

      // Use backend safety_label so we NEVER show HGV SAFE if there's a low bridge
      const label =
        leg.safety_label ||
        (leg.has_conflict
          ? "LOW BRIDGE RISK"
          : leg.near_height_limit
          ? "CHECK HEIGHT"
          : "HGV SAFE");

      badge.textContent = label;

      if (leg.has_conflict) {
        badge.classList.add("badge-danger");
      } else if (leg.near_height_limit) {
        badge.classList.add("badge-warning");
      } else {
        badge.classList.add("badge-safe");
      }

      headerRow.appendChild(title);
      headerRow.appendChild(badge);

      const meta = document.createElement("p");
      meta.className = "route-leg-meta";
      meta.textContent = `Distance: ${leg.distance_km} km · Time: ${leg.duration_min} min`;

      const height = document.createElement("p");
      height.className = "route-leg-meta";
      height.textContent = `Vehicle height: ${leg.vehicle_height_m} m`;

      const bridgeMsg = document.createElement("p");
      bridgeMsg.className = "route-leg-bridge-msg";
      bridgeMsg.textContent = leg.bridge_message;

      card.appendChild(headerRow);
      card.appendChild(meta);
      card.appendChild(height);
      card.appendChild(bridgeMsg);

      // Extra guidance when there's a low bridge risk:
      if (leg.has_conflict) {
        const hint = document.createElement("p");
        hint.className = "route-leg-meta";
        hint.textContent =
          "Suggested: open in Google Maps and choose an alternative route that does not pass the red bridge pin.";
        card.appendChild(hint);
      }

      const mapsBtn = document.createElement("button");
      mapsBtn.className = "primary-btn maps-btn";
      mapsBtn.type = "button";

      if (leg.has_conflict) {
        mapsBtn.textContent = "Open in Google Maps for alternative route";
      } else if (leg.near_height_limit) {
        mapsBtn.textContent =
          "Open in Google Maps (double-check clearance & routes)";
      } else {
        mapsBtn.textContent = "Open in Google Maps (with bridge pins)";
      }

      mapsBtn.addEventListener("click", () => {
        if (leg.google_maps_url) {
          window.open(leg.google_maps_url, "_blank");
        }
      });

      card.appendChild(mapsBtn);

      legsContainer.appendChild(card);
    });
  }

  if (generateBtn) {
    generateBtn.addEventListener("click", (e) => {
      e.preventDefault();
      generateRoute();
    });
  }
});