// web/app.js
// Frontend logic for RouteSafe UI that sits in /web/index.html

document.addEventListener("DOMContentLoaded", () => {
  // Backend base URL (Render backend)
  const API_BASE = "https://routesafe-ai.onrender.com";

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

  function setStatus(message, type = "info") {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.remove("error", "info", "success");
    statusEl.classList.add(type);
  }

  function getFormValues() {
    const vehicleHeight = parseFloat(vehicleHeightInput?.value);
    const originPostcode =
      (originPostcodeInput && originPostcodeInput.value.trim()) ||
      DEFAULT_ORIGIN;
    const deliveryLines = (deliveryPostcodesInput?.value || "")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);

    return { vehicleHeight, originPostcode, deliveryLines };
  }

  async function generateRoute() {
    const { vehicleHeight, originPostcode, deliveryLines } = getFormValues();

    if (!vehicleHeight || !originPostcode || deliveryLines.length === 0) {
      setStatus(
        "Please enter height and at least one delivery postcode.",
        "error"
      );
      return;
    }

    setStatus("Checking route for low bridges...", "info");
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

      const text = await res.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch (err) {
        console.error("Failed to parse backend JSON:", text);
        throw new Error("Backend returned non-JSON response.");
      }

      if (!res.ok) {
        console.error("Backend error status", res.status, data);
        setStatus(
          "Backend error: " + (data.detail || res.statusText),
          "error"
        );
        renderLegs([]);
        return;
      }

      if (data.error) {
        setStatus("Backend error: " + data.error, "error");
        renderLegs(data.legs || []);
        return;
      }

      renderLegs(data.legs || []);
      setStatus("Route generated successfully.", "success");
    } catch (err) {
      console.error(err);
      setStatus(
        "There was a problem generating your route. Please try again.",
        "error"
      );
      renderLegs([]);
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
      const directCard = createDirectLegCard(leg);
      legsContainer.appendChild(directCard);

      // If there is a low bridge risk AND we have an alternative map,
      // show the alt route card underneath.
      if (leg.has_conflict && leg.safe_google_maps_url) {
        const altCard = createAlternativeSafeCard(leg);
        legsContainer.appendChild(altCard);
      }
    });
  }

  function createDirectLegCard(leg) {
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

    if (leg.error) {
      bridgeMsg.textContent = `⚠️ Error for this leg: ${leg.error}`;
    } else if (leg.has_conflict) {
      bridgeMsg.textContent =
        "⚠️ Low bridge on this leg. Route not HGV safe at current height.\n\nDirect route only – see the alternative suggested route card below.";
    } else {
      bridgeMsg.textContent =
        leg.bridge_message ||
        "No low bridges detected within the risk radius for this leg.";
    }

    card.appendChild(headerRow);
    card.appendChild(meta);
    card.appendChild(height);
    card.appendChild(bridgeMsg);

    // Only show a Google Maps button when the leg is NOT marked as unsafe.
    if (!leg.has_conflict && !leg.error && leg.google_maps_url) {
      const mapsBtn = document.createElement("button");
      mapsBtn.className = "primary-btn maps-btn";
      mapsBtn.type = "button";
      mapsBtn.textContent = "Open in Google Maps";
      mapsBtn.addEventListener("click", () => {
        if (leg.google_maps_url) {
          window.open(leg.google_maps_url, "_blank");
        }
      });
      card.appendChild(mapsBtn);
    }

    return card;
  }

  // Alt route card – suggestion only, not guaranteed safe.
  function createAlternativeSafeCard(leg) {
    const card = document.createElement("div");
    card.className = "route-leg-card alt-safe-card";

    const headerRow = document.createElement("div");
    headerRow.className = "route-leg-header-row";

    const title = document.createElement("h3");
    title.className = "route-leg-title";
    title.textContent = `Alternative route – Leg ${leg.index}`;

    const badge = document.createElement("span");
    badge.className = "route-leg-badge badge-warning";
    badge.textContent = "ALT ROUTE (CHECK)";

    headerRow.appendChild(title);
    headerRow.appendChild(badge);

    const meta = document.createElement("p");
    meta.className = "route-leg-meta";

    const altDist =
      typeof leg.alt_distance_km === "number"
        ? leg.alt_distance_km
        : leg.distance_km;
    const altDur =
      typeof leg.alt_duration_min === "number"
        ? leg.alt_duration_min
        : leg.duration_min;

    meta.textContent = `Alt distance: ${altDist} km   ·   Alt time: ${altDur} min`;

    const info = document.createElement("p");
    info.className = "route-leg-bridge-msg";
    info.textContent =
      "Suggested route that tries to steer around the low-bridge area. " +
      "Please visually confirm in Google Maps that it does not pass under the low bridge.";

    const mapsBtn = document.createElement("button");
    mapsBtn.className = "primary-btn maps-btn";
    mapsBtn.type = "button";
    mapsBtn.textContent = "Open in Google Maps (try alt route)";
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

  if (generateBtn) {
    generateBtn.addEventListener("click", (e) => {
      e.preventDefault();
      generateRoute();
    });
  }
});