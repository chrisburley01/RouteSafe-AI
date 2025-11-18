# RouteSafe AI

RouteSafe AI is a simple HGV route safety tool.

**Goal:**  
Drivers / planners can take a photo of a printed route plan (or enter postcodes manually), set their vehicle height, and get a route that **keeps the same drop order but avoids low bridges** and HGV-restricted roads.

## Structure

- `web/` – Web frontend (can be deployed via GitHub Pages).
- `backend/` – API for OCR + HGV-safe routing.

## Frontend (web)

A simple single-page app that lets you:

1. Enter depot postcode
2. Enter delivery postcodes (or use OCR from a photo – coming next)
3. Enter vehicle height
4. Call the backend to:
   - (optionally) extract postcodes from an uploaded image
   - calculate safe legs between each stop in the given order

To run locally:

```bash
cd web
# just open index.html in a browser (or use VS Code Live Server / simple http server)