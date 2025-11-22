// web/app.js
// Frontend logic for RouteSafe UI that sits in /web/index.html

document.addEventListener("DOMContentLoaded", () => {
  // Backend base URL (your Render backend)
  const API_BASE = "https://routesafe-ai.onrender.com";

  const vehicleHeightInput =
    document.getElementById("vehicleHeight") ||
    document.querySelector("[data-role='vehicle-height']");
  const deliveryPostcodesInput =
    document.getElementById("deliveryPostcodes") ||
    document.querySelector("[data-role='delivery-postcodes']");
  const originPostcodeInput =
    document.getElementById("originPostcode") ||
    document.getElementById("depotPostcode");
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
    const originPostcode = (originPostcodeInput?.value || "").trim();
    const deliveryLines = (deliveryPostcodesInput?.value || "")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);

    if (!vehicleHeight || !originPostcode || deliveryLines.length === 0) {
      if (statusEl) {
        statusEl.textContent =
          "Please enter depot, height and at least one delivery postcode.";
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

      const res = await fetch(API_BASE + "/api/route", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const txt = await res.text();
        throw new Error("Server error " + res.status + ": " + txt);
      }

      const data = await res.json();
      console.log("DEBUG response", data);
      renderLegs(data.legs || []);

      if (statusEl) {
        statusEl.textContent = "Route generated successfully.";
        statusEl.style.color = "#1c7c3c";
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
      legsContainer.innerHTML = "<p>No legs returned from backend.</p>";
      return;
    }

    legs.forEach((leg) => {
      const hasAlt = !!leg.has_alternative;

      if (leg.has_conflict && hasAlt) {
        // 🔴 Card 1 – direct route (unsafe)
        legsContainer.appendChild(createDirectUnsafeCard(leg));
        // 🟢 Card 2 – alternative HGV-safe route
        legsContainer.appendChild(createAlternativeSafeCard(leg));
      } else if (leg.has_conflict && !hasAlt) {
        // Only unsafe card, no alternative found
        legsContainer.appendChild(createDirectUnsafeCard(leg));
      } else {
        // Normal safe / near-height leg
        legsContainer.appendChild(createNormalLegCard(leg));
      }
    });
  }

  // -----------------------------------------------------------------------
  // Card factories
  // -----------------------------------------------------------------------

  function createDirectUnsafeCard(leg) {
    const card = document.createElement("div");
    card.className = "route-leg-card unsafe-card";

    const headerRow = document.createElement("div");
    headerRow.className = "route-leg-header-row";

    const title = document.createElement("h3");
    title.className = "route-leg-title";
    title.textContent = `Leg ${leg.index}: ${leg.start_postcode} → ${leg.end_postcode}`;

    const badge = document.createElement("span");
    badge.className = "route-leg-badge badge-danger";
    badge.textContent = "LOW BRIDGE RISK";

    headerRow.appendChild(title);
    headerRow.appendChild(badge);

    const meta = document.createElement("p");
    meta.className = "route-leg-meta";
    meta.textContent = `Distance: ${leg.distance_km} km   ·   Time: ${leg.duration_min} min`;

    const height = document.createElement("p");
    height.className = "route-leg-meta";
    height.textContent = `Vehicle height: ${leg.vehicle_height_m} m`;

    const warning = document.createElement("p");
    warning.className = "route-leg-bridge-msg";
    warning.textContent =
      leg.bridge_message ||
      "⚠️ Low bridge on this leg. Route not HGV safe at current height.";

    const hint = document.createElement("p");
    hint.className = "route-leg-alt-hint";
    hint.textContent =
      "Direct route only – see the alternative HGV-safe route card below.";

    card.appendChild(headerRow);
    card.appendChild(meta);
    card.appendChild(height);
    card.appendChild(warning);
    card.appendChild(hint);

    // ❌ No maps button on unsafe direct route
    return card;
  }

  function createAlternativeSafeCard(leg) {
    const card = document.createElement("div");
    card.className = "route-leg-card alt-safe-card";

    const headerRow = document.createElement("div");
    headerRow.className = "route-leg-header-row";

    const title = document.createElement("h3");
    title.className = "route-leg-title";
    title.textContent = `Alternative HGV-safe route – Leg ${leg.index}`;

    const badge = document.createElement("span");
    badge.className = "route-leg-badge badge-safe";
    badge.textContent = "HGV SAFE (ALT)";

    headerRow.appendChild(title);
    headerRow.appendChild(badge);

    const meta = document.createElement("p");
    meta.className = "route-leg-meta";

    const altDist = leg.alt_distance_km ?? leg.distance_km;
    const altDur = leg.alt_duration_min ?? leg.duration_min;

    meta.textContent = `Alt distance: ${altDist} km   ·   Alt time: ${altDur} min`;

    const info = document.createElement("p");
    info.className = "route-leg-bridge-msg";
    info.textContent =
      "Suggested HGV-safe route that steers around the low bridge area.";

    const mapsBtn = document.createElement("button");
    mapsBtn.className = "primary-btn maps-btn";
    mapsBtn.type = "button";
    mapsBtn.textContent = "Open in Google Maps (safe route)";
    mapsBtn.disabled = !leg.safe_google_maps_url;
    mapsBtn.addEventListener("click", () => {
      if (leg.safe_google_maps_url) {
        window.open(leg.safe_google_maps_url, "_blank");
      }
    });

    card.appendChild(headerRow);
    card.appendChild(meta);
    card.appendChild(info);
    card.appendChild(mapsBtn);

    return card;
  }

  function createNormalLegCard(leg) {
    const card = document.createElement("div");
    card.className = "route-leg-card";

    const headerRow = document.createElement("div");
    headerRow.className = "route-leg-header-row";

    const title = document.createElement("h3");
    title.className = "route-leg-title";
    title.textContent = `Leg ${leg.index}: ${leg.start_postcode} → ${leg.end_postcode}`;

    const badge = document.createElement("span");
    badge.className = "route-leg-badge";

    const label = leg.safety_label || (leg.near_height_limit
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
    meta.textContent = `Distance: ${leg.distance_km} km   ·   Time: ${leg.duration_min} min`;

    const height = document.createElement("p");
    height.className = "route-leg-meta";
    height.textContent = `Vehicle height: ${leg.vehicle_height_m} m`;

    const bridgeMsg = document.createElement("p");
    bridgeMsg.className = "route-leg-bridge-msg";
    bridgeMsg.textContent =
      leg.bridge_message ||
      (leg.near_height_limit
        ? "⚠️ Bridges close to your vehicle height – double-check before travelling."
        : "No low bridges within the risk radius for this leg.");

    const mapsBtn = document.createElement("button");
    mapsBtn.className = "primary-btn maps-btn";
    mapsBtn.type = "button";
    mapsBtn.textContent = "Open in Google Maps";
    mapsBtn.disabled = !leg.google_maps_url;
    mapsBtn.addEventListener("click", () => {
      if (leg.google_maps_url) {
        window.open(leg.google_maps_url, "_blank");
      }
    });

    card.appendChild(headerRow);
    card.appendChild(meta);
    card.appendChild(height);
    card.appendChild(bridgeMsg);
    card.appendChild(mapsBtn);

    return card;
  }

  // -----------------------------------------------------------------------

  if (generateBtn) {
    generateBtn.addEventListener("click", (e) => {
      e.preventDefault();
      generateRoute();
    });
  }
});