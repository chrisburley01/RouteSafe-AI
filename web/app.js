// =======================
// RouteSafe AI – app.js
// =======================

// CHANGE THIS when your backend is hosted somewhere public
// e.g. "https://routesafe-backend.onrender.com"
const API_BASE_URL = "http://127.0.0.1:8000";

const form = document.getElementById("route-form");
const statusEl = document.getElementById("status");
const resultsCard = document.getElementById("results-card");
const legsListEl = document.getElementById("legs-list");
const summaryEl = document.getElementById("summary");
const planPhotoInput = document.getElementById("plan-photo");
const stopsTextarea = document.getElementById("stops");

function setStatus(message, type = "info") {
  statusEl.textContent = message || "";
  statusEl.classList.remove("rs-error", "rs-success");
  if (type === "error") statusEl.classList.add("rs-error");
  if (type === "success") statusEl.classList.add("rs-success");
}

// Turn textarea content into an ordered postcode array
function parsePostcodes(rawText) {
  return rawText
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

// ------------------------------
// Handle form submit (/route)
// ------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const depot = document.getElementById("depot").value.trim();
  const vhRaw = document.getElementById("vehicle-height").value.trim();
  const vehicleHeight = parseFloat(vhRaw);
  const stopsRaw = stopsTextarea.value;

  if (!depot || !vhRaw) {
    setStatus("Please fill depot postcode and vehicle height.", "error");
    return;
  }

  if (Number.isNaN(vehicleHeight)) {
    setStatus("Vehicle height must be a number (e.g. 4.95).", "error");
    return;
  }

  const deliveryPostcodes = parsePostcodes(stopsRaw);
  if (deliveryPostcodes.length === 0) {
    setStatus(
      "Enter at least one delivery postcode or use the photo option to auto-fill.",
      "error"
    );
    return;
  }

  setStatus("Calculating HGV-safe legs (prototype)…");
  resultsCard.classList.add("rs-hidden");
  legsListEl.innerHTML = "";
  summaryEl.textContent = "";

  try {
    const body = {
      depot_postcode: depot,
      delivery_postcodes: deliveryPostcodes,
      vehicle_height_m: vehicleHeight,
    };

    const res = await fetch(`${API_BASE_URL}/route`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Backend error ${res.status}: ${text}`);
    }

    const data = await res.json();
    renderRouteResults(data, vehicleHeight);
    setStatus(
      "Route calculated. Distances/times are approximate until full HGV routing is plugged in.",
      "success"
    );
  } catch (err) {
    console.error(err);
    setStatus(
      "Could not reach RouteSafe AI backend or it returned an error. Check API URL and backend.",
      "error"
    );
  }
});

// ------------------------------
// Render /route response
// ------------------------------
function renderRouteResults(data, vehicleHeight) {
  // Expecting:
  // {
  //   total_distance_km,
  //   total_duration_min,
  //   legs: [
  //     { from_, to, distance_km, duration_min, near_height_limit }
  //   ]
  // }

  const { total_distance_km, total_duration_min, legs } = data;

  summaryEl.textContent = `Total: ${total_distance_km.toFixed(
    1
  )} km · approx ${Math.round(
    total_duration_min
  )} mins · vehicle height ${vehicleHeight.toFixed(2)} m`;

  legsListEl.innerHTML = "";

  legs.forEach((leg, index) => {
    const li = document.createElement("li");
    li.className = "rs-leg-item";

    const main = document.createElement("div");
    main.className = "rs-leg-main";

    const fromTo = document.createElement("div");
    fromTo.className = "rs-leg-fromto";

    const labelFrom = index === 0 ? "Depot" : `Stop ${index}`;
    const labelTo = `Stop ${index + 1}`;

    fromTo.textContent = `${labelFrom} (${leg.from_}) → ${labelTo} (${leg.to})`;

    const meta = document.createElement("div");
    meta.className = "rs-leg-meta";
    meta.textContent = `${leg.distance_km.toFixed(
      1
    )} km · approx ${Math.round(leg.duration_min)} mins`;

    main.appendChild(fromTo);
    main.appendChild(meta);
    li.appendChild(main);

    // Height warning if backend flags it
    if (leg.near_height_limit) {
      const warn = document.createElement("div");
      warn.className = "rs-leg-meta";
      warn.textContent =
        "⚠ Near a height restriction – confirm on in-cab navigation.";
      li.appendChild(warn);
    }

    // "Open in Google Maps" link
    const mapsLink = document.createElement("a");
    mapsLink.className = "rs-leg-meta";
    mapsLink.href = buildGoogleMapsUrl(leg.from_, leg.to);
    mapsLink.target = "_blank";
    mapsLink.rel = "noopener noreferrer";
    mapsLink.textContent = "Open this leg in Google Maps";
    li.appendChild(mapsLink);

    legsListEl.appendChild(li);
  });

  resultsCard.classList.remove("rs-hidden");
}

// Build Google Maps directions URL for a leg
function buildGoogleMapsUrl(fromPostcode, toPostcode) {
  const origin = encodeURIComponent(fromPostcode);
  const dest = encodeURIComponent(toPostcode);
  return `https://www.google.com/maps/dir/?api=1&origin=${origin}&destination=${dest}&travelmode=driving`;
}

// ------------------------------
// OCR: photo of printed plan → /ocr
// ------------------------------
planPhotoInput.addEventListener("change", async () => {
  const file = planPhotoInput.files && planPhotoInput.files[0];
  if (!file) return;

  setStatus("Uploading photo and extracting postcodes…");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API_BASE_URL}/ocr`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`OCR error ${res.status}: ${text}`);
    }

    const data = await res.json();
    const pcs = data.postcodes || [];

    if (!pcs.length) {
      setStatus(
        "No postcodes found in the image. Check lighting/clarity and try again.",
        "error"
      );
      return;
    }

    // Fill textarea with extracted postcodes
    stopsTextarea.value = pcs.join("\n");
    setStatus(
      `Found ${pcs.length} postcodes from the photo. Check them below, then hit "Generate safe legs".`,
      "success"
    );
  } catch (err) {
    console.error(err);
    setStatus(
      "Could not OCR the image. Check backend is running and API_BASE_URL is correct.",
      "error"
    );
  }
});