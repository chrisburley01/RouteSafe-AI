// web/app.js
// Frontend logic for RouteSafe UI that sits in /web/index.html

document.addEventListener("DOMContentLoaded", () => {
  // Backend base URL (Render backend)
  const API_BASE = "https://routesafe-ai.onrender.com";

  // Default origin (depot) – can be overridden if you ever add an origin input.
  const DEFAULT_ORIGIN = "LS270BN";

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
      // -------------------------------
      // Card 1 – DIRECT LEG (always)
      // -------------------------------
      const directCard = document.createElement("div");
      directCard.className = "route-leg-card";

      const headerRow = document.createElement("div");
      headerRow.className = "route-leg-header-row";

      const title = document.createElement("h3");
      title.className = "route-leg-title";
      title.textContent = `Leg ${leg.index}: ${leg.start_postcode} \u2192 ${leg.end_postcode}`;

      const badge = document.createElement("span");
      badge.className = "route-leg-badge";

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
      meta.textContent = `Distance: ${leg.distance_km} km   ·   Time: ${leg.duration_min} min`;

      const height = document.createElement("p");
      height.className = "route-leg-meta";
      height.textContent = `Vehicle height: ${leg.vehicle_height_m} m`;

      const bridgeMsg = document.createElement("p");
      bridgeMsg.className = "route-leg-bridge-msg";
      bridgeMsg.textContent = leg.bridge_message || "";

      // Only show maps button on direct leg if it's actually safe
      if (!leg.has_conflict && leg.google_maps_url) {
        const mapsBtn = document.createElement("button");
        mapsBtn.className = "primary-btn maps-btn";
        mapsBtn.type = "button";
        mapsBtn.textContent = "Open in Google Maps (with bridge pins)";
        mapsBtn.addEventListener("click", () => {
          window.open(leg.google_maps_url, "_blank");
        });
        directCard.appendChild(mapsBtn);
      }

      directCard.appendChild(headerRow);
      directCard.appendChild(meta);
      directCard.appendChild(height);
      directCard.appendChild(bridgeMsg);

      legsContainer.appendChild(directCard);

      // -------------------------------
      // Card 2 – ALTERNATIVE HGV-SAFE ROUTE (optional)
      // -------------------------------
      // Backend may send different alt field names – support all of them.
      const hasAltDistance =
        leg.alt_distance_km !== undefined || leg.alt_distance !== undefined;
      const hasAltTime =
        leg.alt_duration_min !== undefined || leg.alt_time !== undefined;
      const altUrl =
        leg.alt_maps_url ||
        leg.alt_google_maps_url ||
        null;

      const hasAlt =
        leg.has_conflict && (hasAltDistance || hasAltTime || altUrl);

      if (hasAlt) {
        const altDistance =
          leg.alt_distance_km !== undefined
            ? leg.alt_distance_km
            : leg.alt_distance;
        const altDuration =
          leg.alt_duration_min !== undefined
            ? leg.alt_duration_min
            : leg.alt_time;

        const altCard = document.createElement("div");
        altCard.className = "route-leg-card route-leg-card-alt";

        const altHeaderRow = document.createElement("div");
        altHeaderRow.className = "route-leg-header-row";

        const altTitle = document.createElement("h3");
        altTitle.className = "route-leg-title";
        altTitle.textContent = `Alternative HGV-safe route \u2013 Leg ${leg.index}`;

        const altBadge = document.createElement("span");
        altBadge.className = "route-leg-badge badge-safe";
        altBadge.textContent = "HGV SAFE (ALT)";

        altHeaderRow.appendChild(altTitle);
        altHeaderRow.appendChild(altBadge);

        const altMeta = document.createElement("p");
        altMeta.className = "route-leg-meta";
        altMeta.textContent = `Alt distance: ${
          altDistance !== undefined ? altDistance : "?"
        } km   ·   Alt time: ${
          altDuration !== undefined ? altDuration : "?"
        } min`;

        const altCopy = document.createElement("p");
        altCopy.className = "route-leg-bridge-msg";
        altCopy.textContent =
          "Suggested HGV-safe route that steers around the low bridge area.";

        altCard.appendChild(altHeaderRow);
        altCard.appendChild(altMeta);
        altCard.appendChild(altCopy);

        if (altUrl) {
          const altBtn = document.createElement("button");
          altBtn.className = "primary-btn maps-btn";
          altBtn.type = "button";
          altBtn.textContent = "Open in Google Maps (safe route)";
          altBtn.addEventListener("click", () => {
            window.open(altUrl, "_blank");
          });
          altCard.appendChild(altBtn);
        }

        legsContainer.appendChild(altCard);
      }
    });
  }

  if (generateBtn) {
    generateBtn.addEventListener("click", (e) => {
      e.preventDefault();
      generateRoute();
    });
  }
});