// =======================
// RouteSafe AI – app.js
// =======================

// LIVE backend URL (Render)
const API_BASE_URL = "https://routesafe-ai.onrender.com";

const form = document.getElementById("route-form");
const statusEl = document.getElementById("status");
const resultsCard = document.getElementById("results-card");
const legsListEl = document.getElementById("legs-list");
const summaryEl = document.getElementById("summary");
const planPhotoInput = document.getElementById("plan-photo");
const stopsTextarea = document.getElementById("stops");

// ---------- helpers ---------- //

function setStatus(message, type = "info") {
  statusEl.textContent = message || "";
  statusEl.classList.remove("rs-error", "rs-success");
  if (type === "error") statusEl.classList.add("rs-error");
  if (type === "success") statusEl.classList.add("rs-success");
}

function parsePostcodes(rawText) {
  return rawText
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function buildGoogleMapsUrl(fromPostcode, toPostcode) {
  const origin = encodeURIComponent(fromPostcode);
  const dest = encodeURIComponent(toPostcode);
  return `https://www.google.com/maps/dir/?api=1&origin=${origin}&destination=${dest}&travelmode=driving`;
}

// ---------- form submit -> /route ---------- //

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const depot = document.getElementById("depot").value.trim();
  const vhRaw = document.getElementById("vehicle-height").value.trim();
  const vehicleHeight = parseFloat(vhRaw);
  const stopsRaw = stopsTextarea.value;

  if (!depot || !vhRaw) {
    setStatus("Please fill depot postcode and vehicle height.", "error");
    resultsCard.classList.add("rs-hidden");
    return;
  }

  if (Number.isNaN(vehicleHeight)) {
    setStatus("Vehicle height must be a number (e.g. 4.95).", "error");
    resultsCard.classList.add("rs-hidden");
    return;
  }

  const deliveryPostcodes = parsePostcodes(stopsRaw);
  if (deliveryPostcodes.length === 0) {
    setStatus(
      "Enter at least one delivery postcode or use the photo option to auto-fill.",
      "error"
    );
    resultsCard.classList.add("rs-hidden");
    return;
  }

  setStatus("Calculating safe legs…");
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Backend error ${res.status}: ${text}`);
    }

    const data = await res.json();
    renderRouteResults(data, vehicleHeight);
    setStatus(
      "Route calculated. Distances/times rough until HGV router is plugged in, but bridge checks are live.",
      "success"
    );
  } catch (err) {
    console.error(err);
    setStatus(
      "Could not reach RouteSafe AI backend or it returned an error. Check Render service & logs.",
      "error"
    );
  }
});

// ---------- render /route response ---------- //

function renderRouteResults(data, vehicleHeight) {
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

    const topLine = document.createElement("div");
    topLine.className = "rs-leg-main";

    const labelFrom = index === 0 ? "Depot" : `Stop ${index}`;
    const labelTo = `Stop ${index + 1}`;

    const fromTo = document.createElement("div");
    fromTo.className = "rs-leg-fromto";
    fromTo.textContent = `${labelFrom} (${leg.from_}) → ${labelTo} (${leg.to})`;

    const meta = document.createElement("div");
    meta.className = "rs-leg-meta";
    meta.textContent = `${leg.distance_km.toFixed(
      1
    )} km · approx ${Math.round(leg.duration_min)} mins`;

    topLine.appendChild(fromTo);
    topLine.appendChild(meta);
    li.appendChild(topLine);

    // Height warning from backend
    if (leg.near_height_limit) {
      const warn = document.createElement("div");
      warn.className = "rs-leg-meta rs-leg-warning";
      warn.textContent =
        "⚠ Near a height restriction – double-check on in-cab navigation.";
      li.appendChild(warn);
    }

    // Open leg in Google Maps
    const mapsLink = document.createElement("a");
    mapsLink.className = "rs-leg-meta rs-leg-link";
    mapsLink.href = buildGoogleMapsUrl(leg.from_, leg.to);
    mapsLink.target = "_blank";
    mapsLink.rel = "noopener noreferrer";
    mapsLink.textContent = "Open this leg in Google Maps";
    li.appendChild(mapsLink);

    legsListEl.appendChild(li);
  });

  resultsCard.classList.remove("rs-hidden");
}

// ---------- /ocr: photo of printed plan ---------- //

planPhotoInput.addEventListener("change", async () => {
  const file = planPhotoInput.files && planPhotoInput.files[0];
  if (!file) return;

  setStatus("Uploading photo and extracting postcodes…");
  resultsCard.classList.add("rs-hidden");

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

    stopsTextarea.value = pcs.join("\n");
    setStatus(
      `Found ${pcs.length} postcodes from the photo. Check them, then hit "Generate safe legs".`,
      "success"
    );
  } catch (err) {
    console.error(err);
    setStatus(
      "Could not OCR the image. Check backend /ocr implementation and logs.",
      "error"
    );
  }
});