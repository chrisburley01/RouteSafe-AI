// web/app.js
// RouteSafe AI frontend
// Version: 0.6.0  (dual cards on LOW BRIDGE: red direct, green alternative)

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

  function createLegMetaBlock(leg) {
    const fragment = document.createDocumentFragment();

    const meta = document.createElement("p");
    meta.className = "route-leg-meta";
    meta.textContent = `Distance: ${leg.distance_km} km · Time: ${leg.duration_min} min`;

    const height = document.createElement("p");
    height.className = "route-leg-meta";
    height.textContent = `Vehicle height: ${leg.vehicle_height_m} m`;

    fragment.appendChild(meta);
    fragment.appendChild(height);

    return fragment;
  }

  function renderLegs(legs) {
    if (!legsContainer) return;
    legsContainer.innerHTML = "";

    if (!legs || legs.length === 0) {
      legsContainer.innerHTML = "<p>No legs generated yet.</p>";
      return;
    }

    legs.forEach((leg) => {
      // For non-conflict legs: single green/amber card, as before
      if (!leg.has_conflict) {
        const card = document.createElement("div");
        card.className = "route-leg-card";

        const headerRow = document.createElement("div");
        headerRow.className = "route-leg-header-row";

        const title = document.createElement("h3");
        title.className = "route-leg-title";
        title.textContent = `Leg ${leg.index}: ${leg.start_postcode} → ${leg.end_postcode}`;

        const badge = document.createElement("span");
        badge.className = "route-leg-badge";

        const label =
          leg.safety_label ||
          (leg.near_height_limit ? "CHECK HEIGHT" : "HGV SAFE");
        badge.textContent = label;

        if (leg.near_height_limit) {
          badge.classList.add("badge-warning");
        } else {
          badge.classList.add("badge-safe");
        }

        headerRow.appendChild(title);
        headerRow.appendChild(badge);

        card.appendChild(headerRow);
        card.appendChild(createLegMetaBlock(leg));

        const bridgeMsg = document.createElement("p");
        bridgeMsg.className = "route-leg-bridge-msg";
        bridgeMsg.textContent = leg.bridge_message;
        card.appendChild(bridgeMsg);

        const mapsBtn = document.createElement("button");
        mapsBtn.className = "primary-btn maps-btn";
        mapsBtn.type = "button";
        mapsBtn.textContent = leg.near_height_limit
          ? "Open in Google Maps (double-check clearance)"
          : "Open in Google Maps (with bridge pins)";
        mapsBtn.addEventListener("click", () => {
          if (leg.google_maps_url) {
            window.open(leg.google_maps_url, "_blank");
          }
        });

        card.appendChild(mapsBtn);
        legsContainer.appendChild(card);
        return;
      }

      // If has_conflict === true:
      // 🔴 Card 1 – direct route, unsafe, NO Maps button
      const unsafeCard = document.createElement("div");
      unsafeCard.className = "route-leg-card route-leg-card-unsafe";

      const unsafeHeaderRow = document.createElement("div");
      unsafeHeaderRow.className = "route-leg-header-row";

      const unsafeTitle = document.createElement("h3");
      unsafeTitle.className = "route-leg-title";
      unsafeTitle.textContent = `Leg ${leg.index}: ${leg.start_postcode} → ${leg.end_postcode}`;

      const unsafeBadge = document.createElement("span");
      unsafeBadge.className = "route-leg-badge badge-danger";
      unsafeBadge.textContent = "LOW BRIDGE RISK – DIRECT ROUTE";

      unsafeHeaderRow.appendChild(unsafeTitle);
      unsafeHeaderRow.appendChild(unsafeBadge);

      unsafeCard.appendChild(unsafeHeaderRow);
      unsafeCard.appendChild(createLegMetaBlock(leg));

      const unsafeMsg = document.createElement("p");
      unsafeMsg.className = "route-leg-bridge-msg";
      unsafeMsg.textContent =
        "⚠️ Low bridge on this direct route. Do NOT follow this route at the current vehicle height.";
      unsafeCard.appendChild(unsafeMsg);

      const unsafeHint = document.createElement("p");
      unsafeHint.className = "route-leg-meta";
      unsafeHint.textContent =
        "Use the green HGV-safe route card below instead.";
      unsafeCard.appendChild(unsafeHint);

      legsContainer.appendChild(unsafeCard);

      // 🟢 Card 2 – suggested alternative with Maps button
      const safeCard = document.createElement("div");
      safeCard.className = "route-leg-card route-leg-card-safe-alt";

      const safeHeaderRow = document.createElement("div");
      safeHeaderRow.className = "route-leg-header-row";

      const safeTitle = document.createElement("h3");
      safeTitle.className = "route-leg-title";
      safeTitle.textContent = `Leg ${leg.index}: Suggested HGV-safe route`;

      const safeBadge = document.createElement("span");
      safeBadge.className = "route-leg-badge badge-safe";
      safeBadge.textContent = "HGV-SAFE ROUTE";

      safeHeaderRow.appendChild(safeTitle);
      safeHeaderRow.appendChild(safeBadge);

      safeCard.appendChild(safeHeaderRow);
      safeCard.appendChild(createLegMetaBlock(leg));

      const safeMsg = document.createElement("p");
      safeMsg.className = "route-leg-bridge-msg";
      safeMsg.textContent =
        "Open in Google Maps and choose an alternative route that does not pass the red bridge pin. This is your HGV-safe route for this leg.";
      safeCard.appendChild(safeMsg);

      const mapsBtnAlt = document.createElement("button");
      mapsBtnAlt.className = "primary-btn maps-btn";
      mapsBtnAlt.type = "button";
      mapsBtnAlt.textContent = "Open in Google Maps for HGV-safe route";
      mapsBtnAlt.addEventListener("click", () => {
        if (leg.google_maps_url) {
          window.open(leg.google_maps_url, "_blank");
        }
      });

      safeCard.appendChild(mapsBtnAlt);
      legsContainer.appendChild(safeCard);
    });
  }

  if (generateBtn) {
    generateBtn.addEventListener("click", (e) => {
      e.preventDefault();
      generateRoute();
    });
  }
});