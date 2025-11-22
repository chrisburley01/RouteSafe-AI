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