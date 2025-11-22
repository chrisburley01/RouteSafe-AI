# ===============================
# bridge_engine.py
# ===============================
# Simple low-bridge risk engine for RouteSafe-AI.
#
# Given a full route (list of [lon, lat] points) and vehicle height,
# it:
#   - finds nearby bridges
#   - flags conflicts (bridge < vehicle height)
#   - flags near-miss (bridge < vehicle height + 0.25m)
#   - returns summary + warning list

from dataclasses import dataclass
from typing import Optional, List, Tuple
from pathlib import Path
import math
import pandas as pd


EARTH_RADIUS_M = 6371000.0  # metres


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------
@dataclass
class Bridge:
    lat: float
    lon: float
    height_m: float


@dataclass
class BridgeWarning:
    bridge: Bridge
    distance_m: float
    severity: str  # "conflict" or "near"
    message: str


@dataclass
class BridgeCheckResult:
    has_conflict: bool
    near_height_limit: bool
    nearest_bridge: Optional[Bridge]
    nearest_distance_m: Optional[float]
    warnings: List[BridgeWarning]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance between two WGS84 points in metres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


# ------------------------------------------------------------------
# Bridge engine
# ------------------------------------------------------------------
class BridgeEngine:
    """
    Loads low-bridge data and can check a full route for risks.

    Expects CSV with columns:
        lat, lon, height_m
    (this matches your bridge_heights_clean.csv)
    """

    def __init__(
        self,
        csv_path: str = "bridge_heights_clean.csv",
        search_radius_m: float = 300.0,
        conflict_clearance_m: float = 0.0,
        near_clearance_m: float = 0.25,
    ):
        self.search_radius_m = search_radius_m
        self.conflict_clearance_m = conflict_clearance_m
        self.near_clearance_m = near_clearance_m

        csv_full = Path(csv_path)
        if not csv_full.is_file():
            # Allow relative from this file's directory as well
            csv_full = Path(__file__).resolve().parent / csv_path

        if not csv_full.is_file():
            raise FileNotFoundError(f"Bridge CSV not found at {csv_full}")

        df = pd.read_csv(csv_full)

        # Normalise column names
        cols = {c.lower(): c for c in df.columns}
        lat_col = cols.get("lat") or cols.get("latitude")
        lon_col = cols.get("lon") or cols.get("longitude")
        h_col = cols.get("height_m") or cols.get("height")

        if not (lat_col and lon_col and h_col):
            raise ValueError(
                "bridge_heights_clean.csv must have lat, lon, height_m columns"
            )

        self.bridges: List[Bridge] = []
        for _, row in df.iterrows():
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
                h = float(row[h_col])
            except (TypeError, ValueError):
                continue
            self.bridges.append(Bridge(lat=lat, lon=lon, height_m=h))

    # --------------------------------------------------------------
    def check_route(
        self, route_lonlat: List[Tuple[float, float]], vehicle_height_m: float
    ) -> BridgeCheckResult:
        """
        route_lonlat: list of (lon, lat) points from ORS.
        """

        if not route_lonlat or not self.bridges:
            return BridgeCheckResult(
                has_conflict=False,
                near_height_limit=False,
                nearest_bridge=None,
                nearest_distance_m=None,
                warnings=[],
            )

        # Quick bounding box to skip far-away bridges
        lons = [p[0] for p in route_lonlat]
        lats = [p[1] for p in route_lonlat]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        # Expand box a little
        pad_deg = 0.01  # ~1km in lat
        min_lon -= pad_deg
        max_lon += pad_deg
        min_lat -= pad_deg
        max_lat += pad_deg

        relevant_bridges = [
            b
            for b in self.bridges
            if (min_lon <= b.lon <= max_lon) and (min_lat <= b.lat <= max_lat)
        ]

        has_conflict = False
        near_limit = False
        nearest_bridge: Optional[Bridge] = None
        nearest_distance_m: Optional[float] = None
        warnings: List[BridgeWarning] = []

        for bridge in relevant_bridges:
            # Find closest distance from bridge to any route point
            min_dist = None
            for lon, lat in route_lonlat:
                d = haversine_m(lat, lon, bridge.lat, bridge.lon)
                if min_dist is None or d < min_dist:
                    min_dist = d

            if min_dist is None or min_dist > self.search_radius_m:
                continue  # too far from the route to care

            # Height logic
            clearance = bridge.height_m - vehicle_height_m

            if clearance < self.conflict_clearance_m:
                has_conflict = True
                severity = "conflict"
                msg = (
                    f"Bridge {bridge.height_m:.2f} m within "
                    f"{min_dist:.0f} m of route (< vehicle height)."
                )
            elif clearance < self.near_clearance_m:
                near_limit = True
                severity = "near"
                msg = (
                    f"Bridge {bridge.height_m:.2f} m within "
                    f"{min_dist:.0f} m of route (near height limit)."
                )
            else:
                # safe, but still track nearest for info
                severity = ""
                msg = ""

            if severity:
                warnings.append(
                    BridgeWarning(
                        bridge=bridge,
                        distance_m=min_dist,
                        severity=severity,
                        message=msg,
                    )
                )

            # Track nearest bridge to route, regardless of severity
            if nearest_distance_m is None or min_dist < nearest_distance_m:
                nearest_distance_m = min_dist
                nearest_bridge = bridge

        # Sort warnings by severity then distance
        severity_order = {"conflict": 0, "near": 1}
        warnings.sort(
            key=lambda w: (severity_order.get(w.severity, 99), w.distance_m)
        )

        return BridgeCheckResult(
            has_conflict=has_conflict,
            near_height_limit=near_limit,
            nearest_bridge=nearest_bridge,
            nearest_distance_m=nearest_distance_m,
            warnings=warnings,
        )