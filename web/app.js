// web/app.js

// Point this at your backend
const API_BASE_URL = "http://127.0.0.1:8000"; // change when deployed

const form = document.getElementById("route-form");
const statusEl = document.getElementById("status");
const resultsCard = document.getElementById("results-card");
const legsListEl = document.getElementById("legs-list");
const summaryEl = document.getElementById("summary");
const planPhotoInput = document.getElementById("plan-photo");
const stopsTextarea = document.getElementById("stops");

function setStatus(message, type = "info") {
  statusEl.textContent = message;
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

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const depot = document.getElementById("depot").value.trim();
  const vehicleHeightVal = document.getElementById("vehicle-height").value;
  const vehicleHeight = parseFloat(vehicleHeightVal);
  const stopsRaw = stopsTextarea.value;

  if (!depot || !vehicleHeightVal || !stopsRaw) {
    setStatus("Please fill depot, vehicle height and at least one stop.", "error");
    return;
  }

  const deliveryPostcodes = parsePostcodes(stopsRaw);
  if (deliveryPostcodes.length === 0) {
    setStatus("Please enter at least one valid delivery postcode.", "error");
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
    setStatus("Route calculated (distance/time is approximate in this prototype).", "success");
  } catch (err) {
    console.error(err);
    setStatus(
      "Could not reach RouteSafe AI backend or it returned an error. Check API URL and logs.",
      "error"
    );
  }
});

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
    )} km · ${Math.round(leg.duration_min)} mins`;

    main.appendChild(fromTo);
    main.appendChild(meta);
    li.appendChild(main);

    if (leg.near_height_limit) {
      const warn = document.createElement("div");
      warn.className = "rs-leg-meta";
      warn.textContent =
        "⚠ Near a height restriction – double-check in-cab navigation.";
      li.appendChild(warn);
    }

    legsListEl.appendChild(li);
  });

  resultsCard.classList.remove("rs-hidden");
}

// ---- OCR flow for photo of plan ---- //

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
      setStatus("No postcodes found in image. Check clarity and try again.", "error");
      return;
    }

    // Put the extracted postcodes into the textarea, one per line
    stopsTextarea.value = pcs.join("\n");
    setStatus(
      `Found ${pcs.length} postcodes. Check/amend them below, then hit "Generate safe legs".`,
      "success"
    );
  } catch (err) {
    console.error(err);
    setStatus(
      "Could not OCR the image. Make sure backend is running and the photo is clear.",
      "error"
    );
  }
});