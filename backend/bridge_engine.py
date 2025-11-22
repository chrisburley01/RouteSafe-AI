# ===========================
# bridge_engine.py
# ===========================
#
# Loads low-bridge data from CSV and checks a route geometry
# (list of [lon, lat] points from ORS) for nearby low bridges.
#
# CSV expectations:
#   bridge_heights_clean.csv with columns:
#       lat, lon, height_m
#

from dataclasses import dataclass
from typing import Optional, List, Tuple
import math
import csv

EARTH_RADIUS_M = 6_371_000.0  # metres


@dataclass
class Bridge:
    lat: float
    lon: float
    height_m: float


@dataclass
class BridgeCheckResult:
    has_conflict: bool
    near_height_limit: bool
    nearest_bridge: Optional[Bridge]
    nearest_distance_m: Optional[float]


class BridgeEngine:
    """
    Loads low-bridge data and checks a *route* (polyline) for
    nearby bridges given a vehicle height (metres).

    Usage:

        engine = BridgeEngine("bridge_heights_clean.csv")
        result = engine.check_route(coords, vehicle_height_m=4.9)

        coords is a list of [lon, lat] from ORS GeoJSON geometry.
    """

    def __init__(
        self,
        csv_path: str = "bridge_heights_clean.csv",
        search_radius_m: float = 300.0,
        conflict_clearance_m: float = 0.0,
        near_clearance_m: float = 0.25,
    ):
        self.csv_path = csv_path
        self.search_radius_m = float(search_radius_m)
        self.conflict_clearance_m = float(conflict_clearance_m)
        self.near_clearance_m = float(near_clearance_m)

        self.bridges: List[Bridge] = []
        self._load_csv()

    # ----------------------- CSV loader -----------------------

    def _load_csv(self) -> None:
        """
        Load bridges from CSV into memory.

        Expects columns: lat, lon, height_m
        """
        try:
            with open(self.csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        lat = float(row["lat"])
                        lon = float(row["lon"])
                        height = float(row["height_m"])
                        self.bridges.append(Bridge(lat=lat, lon=lon, height_m=height))
                    except Exception:
                        # Skip any bad row quietly
                        continue
        except FileNotFoundError:
            # If the file isn't there we just work with no bridges
            self.bridges = []

    # ----------------------- Geo helpers -----------------------

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Great-circle distance in metres between two points.
        """
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = phi2 - phi1
        dlambda = math.radians(lon2 - lon1)

        a = (
            math.sin(dphi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return EARTH_RADIUS_M * c

    # ----------------------- Main check -----------------------

    def check_route(
        self,
        route_coords_lonlat: List[List[float]],
        vehicle_height_m: float,
    ) -> BridgeCheckResult:
        """
        route_coords_lonlat: list of [lon, lat] points along the route.
        vehicle_height_m: full running height of the vehicle.
        """

        if not self.bridges or not route_coords_lonlat:
            return BridgeCheckResult(
                has_conflict=False,
                near_height_limit=False,
                nearest_bridge=None,
                nearest_distance_m=None,
            )

        vehicle_height_m = float(vehicle_height_m)

        # Convert route coords to (lat, lon) tuples for easier handling
        # ORS gives [lon, lat], so we flip them.
        route_latlon: List[Tuple[float, float]] = [
            (float(lat), float(lon)) for lon, lat in route_coords_lonlat
        ]

        # Bounding box filter to make it efficient
        lats = [lat for lat, _ in route_latlon]
        lons = [lon for _, lon in route_latlon]

        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)

        # Expand by a margin derived from search radius
        deg_margin = self.search_radius_m / 111_000.0  # approx degrees per metre

        lat_min_bb = min_lat - deg_margin
        lat_max_bb = max_lat + deg_margin
        lon_min_bb = min_lon - deg_margin
        lon_max_bb = max_lon + deg_margin

        has_conflict = False
        near_limit = False
        nearest_bridge: Optional[Bridge] = None
        nearest_distance_m: Optional[float] = None

        for bridge in self.bridges:
            # Quick bbox rejection
            if not (lat_min_bb <= bridge.lat <= lat_max_bb):
                continue
            if not (lon_min_bb <= bridge.lon <= lon_max_bb):
                continue

            # Compute min distance from this bridge to any route point
            min_d_for_bridge = None
            for lat_r, lon_r in route_latlon:
                d = self._haversine_m(lat_r, lon_r, bridge.lat, bridge.lon)
                if (min_d_for_bridge is None) or (d < min_d_for_bridge):
                    min_d_for_bridge = d

            if min_d_for_bridge is None:
                continue

            # Only treat as "near" if within search radius
            if min_d_for_bridge > self.search_radius_m:
                continue

            # Update nearest bridge candidate
            if (nearest_distance_m is None) or (min_d_for_bridge < nearest_distance_m):
                nearest_distance_m = min_d_for_bridge
                nearest_bridge = bridge

            # Height logic
            # 1) Hard conflict: bridge + clearance < vehicle
            if bridge.height_m + self.conflict_clearance_m < vehicle_height_m:
                has_conflict = True
            else:
                # 2) Near limit: within near_clearance_m of vehicle height
                if abs(bridge.height_m - vehicle_height_m) <= self.near_clearance_m:
                    near_limit = True

        return BridgeCheckResult(
            has_conflict=has_conflict,
            near_height_limit=near_limit,
            nearest_bridge=nearest_bridge,
            nearest_distance_m=nearest_distance_m,
        )