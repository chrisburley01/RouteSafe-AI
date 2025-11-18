// web/app.js

// Set this to where your backend runs (local dev or deployed)
const API_BASE_URL = "http://127.0.0.1:8000"; // change when backend is live

const form = document.getElementById("route-form");
const statusEl = document.getElementById("status");
const resultsCard = document.getElementById("results-card");
const legsListEl = document.getElementById("legs-list");
const summaryEl = document.getElementById("summary");
const planPhotoInput = document.getElementById("plan-photo");

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
  const vehicleHeight = parseFloat(
    document.getElementById("vehicle-height").value
  );
  const stopsRaw = document.getElementById("stops").value;

  if (!depot || !vehicleHeight || !stopsRaw) {
    setStatus("Please fill depot, vehicle height and at least one stop.", "error");
    return;
  }

  const deliveryPostcodes = parsePostcodes(stopsRaw);
  if (deliveryPostcodes.length === 0) {
    setStatus("Please enter at least one delivery postcode.", "error");
    return;
  }

  setStatus("Calculating HGV-safe route…");
  resultsCard.classList.add("rs-hidden");
  legsListEl.innerHTML = "";
  summaryEl.textContent = "";

  try {
    const body = {
      depot_postcode: depot,
      delivery_postcodes: deliveryPostcodes,
      vehicle_height_m: vehicleHeight,
    };

    // Call backend /route endpoint
    const res = await fetch(`${API_BASE_URL}/route`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      throw new Error(`Backend error: ${res.status}`);
    }

    const data = await res.json();
    renderRouteResults(data, vehicleHeight);
    setStatus("Done.", "success");
  } catch (err) {
    console.error(err);
    setStatus(
      "Could not reach RouteSafe AI backend. Check API URL or try again.",
      "error"
    );
  }
});

// Render backend /route response
function renderRouteResults(data, vehicleHeight) {
  // Expected shape (you can tweak backend to match this):
  // {
  //   total_distance_km: number,
  //   total_duration_min: number,
  //   legs: [
  //     {
  //       from: "LS27 0LF",
  //       to: "WF3 1AB",
  //       distance_km: number,
  //       duration_min: number,
  //       near_height_limit: boolean
  //     },
  //     ...
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
    fromTo.textContent = `${index === 0 ? "Depot" : `Stop ${index}`} → Stop ${
      index + 1
    }: ${leg.to}`;

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
        "⚠ Passes near a height restriction – take extra care / confirm in cab.";
      li.appendChild(warn);
    }

    legsListEl.appendChild(li);
  });

  resultsCard.classList.remove("rs-hidden");
}

// (Future) hook up OCR endpoint when ready
planPhotoInput.addEventListener("change", () => {
  if (planPhotoInput.files && planPhotoInput.files[0]) {
    setStatus(
      "Photo selected. OCR-based postcode extraction will be wired in a later version.",
      "info"
    );
  }
});