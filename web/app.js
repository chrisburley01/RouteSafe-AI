function renderLegMap(geometry, mapId) {
  const el = document.getElementById(mapId);
  if (!el) return;

  // Force visible height so Leaflet can draw
  el.style.minHeight = "210px";

  if (!geometry || !geometry.length || typeof L === "undefined") {
    el.innerHTML =
      '<div class="hint" style="padding:0.6rem;">No map data available for this leg.</div>';
    return;
  }

  const latLngs = geometry.map(([lon, lat]) => [lat, lon]);

  // Delay to ensure the div is actually laid out on mobile
  setTimeout(() => {
    const map = L.map(mapId, {
      zoomControl: false,
      attributionControl: false,
    });

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
    }).addTo(map);

    const line = L.polyline(latLngs, { weight: 4 }).addTo(map);
    map.fitBounds(line.getBounds(), { padding: [10, 10] });
  }, 50);
}