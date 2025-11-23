// RouteSafe-AI frontend v5.0 – multi-leg + bridge risk highlighting

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("routeForm");
  const depotInput = document.getElementById("depotPostcode");
  const deliveriesInput = document.getElementById("deliveryPostcodes");
  const heightInput = document.getElementById("vehicleHeight");
  const avoidCheckbox = document.getElementById("avoidLowBridges");
  const statusEl = document.getElementById("statusMessage");
  const resultsCard = document.getElementById("resultsCard");
  const legsContainer = document.getElementById("legsContainer");

  const API_BASE = window.location.origin; // same Render service

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    statusEl.textContent = "";
    legsContainer.innerHTML = "";
    resultsCard.style.display = "none";

    const depot = depotInput.value.trim();
    const height = parseFloat(heightInput.value);
    const avoidLow = !!avoidCheckbox.checked;

    const deliveries = deliveriesInput.value
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);

    if (!depot || deliveries.length === 0 || !height || isNaN(height)) {
      statusEl.textContent =
        "Please enter a depot, at least one delivery postcode, and a valid height in metres.";
      return;
    }

    // Build legs: depot -> drop1, drop1 -> drop2, etc.
    const legs = [];
    let last = depot;
    deliveries.forEach((pc) => {
      legs.push({ start: last, end: pc });
      last = pc;
    });

    statusEl.textContent = "Checking legs for low bridges…";
    form.querySelector("#generateBtn").disabled = true;

    try {
      const results = [];
      for (let i = 0; i < legs.length; i++) {
        const leg = legs[i];
        const res = await fetch(`${API_BASE}/api/route`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            start: leg.start,
            end: leg.end,
            vehicle_height_m: height,
            avoid_low_bridges: avoidLow,
          }),
        });

        if (!res.ok) {
          const text = await res.text();
          throw new Error(`Leg ${i + 1} failed: ${text}`);
        }

        const data = await res.json();
        results.push({ ...data, legIndex: i + 1 });
      }

      renderLegs(results);
      resultsCard.style.display = "block";
      statusEl.textContent = "Route generated successfully.";
    } catch (err) {
      console.error(err);
      statusEl.textContent =
        "Sorry – something went wrong talking to the routing engine. Please try again.";
    } finally {
      form.querySelector("#generateBtn").disabled = false;
    }
  });

  function renderLegs(results) {
    legsContainer.innerHTML = "";

    results.forEach((res, idx) => {
      const title = `Leg ${idx + 1}: ${res.start_used} → ${res.end_used}`;
      const km = (res.distance_m / 1000).toFixed(1);
      const minutes = Math.round(res.duration_s / 60);

      const hasConflict = !!res.bridge_risk?.has_conflict;
      const nearLimit = !!res.bridge_risk?.near_height_limit;

      const legCard = document.createElement("article");
      legCard.className = "leg-card" + (hasConflict ? " leg-card--danger" : "");

      const titleRow = document.createElement("div");
      titleRow.className = "leg-title-row";

      const h3 = document.createElement("h3");
      h3.className = "leg-title";
      h3.textContent = title;

      const chip = document.createElement("span");
      chip.className = "leg-chip";
      chip.textContent = hasConflict
        ? "Low bridge risk"
        : nearLimit
        ? "Near height limit"
        : "Clear (no low bridge found)";

      titleRow.appendChild(h3);
      titleRow.appendChild(chip);

      const meta = document.createElement("p");
      meta.className = "leg-meta";
      meta.textContent = `Distance: ${km} km · Time: ${minutes} min`;

      legCard.appendChild(titleRow);
      legCard.appendChild(meta);

      if (hasConflict) {
        const warn = document.createElement("div");
        warn.className = "leg-warning";

        const icon = document.createElement("span");
        icon.className = "leg-warning-icon";
        icon.textContent = "⚠️";

        const text = document.createElement("p");
        text.style.margin = "0";
        text.textContent =
          "Low bridge on this leg. Route not HGV safe at current height. Direct route only – preview in Google Maps and use with caution.";

        warn.appendChild(icon);
        warn.appendChild(text);
        legCard.appendChild(warn);
      }

      // Google Maps preview button
      const mapsLink = document.createElement("a");
      mapsLink.className = "leg-maps-btn";
      mapsLink.target = "_blank";
      mapsLink.rel = "noopener noreferrer";
      mapsLink.href =
        "https://www.google.com/maps/dir/?api=1&origin=" +
        encodeURIComponent(res.start_used) +
        "&destination=" +
        encodeURIComponent(res.end_used);
      mapsLink.textContent = "Open in Google Maps (preview route)";

      legCard.appendChild(mapsLink);

      legsContainer.appendChild(legCard);
    });
  }
});