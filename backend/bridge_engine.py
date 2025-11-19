# bridge_engine.py
#
# Uses cleaned Network Rail bridge data (lat, lon, height_m)
# to check a straight-line leg for low-bridge risks.

from dataclasses import dataclass
from typing import Optional, List, Tuple

import math
import pandas as pd


EARTH_RADIUS_M = 6371000.0  # metres


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
    Loads low-bridge data and can check a *leg* (start → end)
    for nearby bridges, using vehicle height in metres.

    Expects CSV with columns:
        lat, lon, height_m
    """

    def __init__(
        self,
        csv_path: str = "bridge_heights_clean.csv",
        search_radius_m: float = 300.0,
        conflict_clearance_m: float = 0.0,
        near_clearance_m: float = 0.25,
    ):
        """
        :param csv_path: path to cleaned bridge CSV (lat, lon, height_m)
        :param search_radius_m: only consider bridges within this distance of leg
        :param conflict_clearance_m: if vehicle_height_m + this > bridge.height_m => hard conflict
        :param near_clearance_m: if vehicle_height_m + this > bridge.height_m => near-height warning
        """
        self.csv_path = csv_path
        self.search_radius_m = float(search_radius_m)
        self.conflict_clearance_m = float(conflict_clearance_m)
        self.near_clearance_m = float(near_clearance_m)

        df = pd.read_csv(self.csv_path)

        required_cols = {"lat", "lon", "height_m"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"Bridge CSV is missing required columns: {missing}")

        # Clean and keep only rows with valid values
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df["height_m"] = pd.to_numeric(df["height_m"], errors="coerce")

        df = df.dropna(subset=["lat", "lon", "height_m"])

        self.bridges: List[Bridge] = [
            Bridge(lat=float(r["lat"]), lon=float(r["lon"]), height_m=float(r["height_m"]))
            for _, r in df.iterrows()
        ]

        print(f"[BridgeEngine] Loaded {len(self.bridges)} bridges from {self.csv_path}.")

    # ---------------- geometry helpers ---------------- #

    @staticmethod
    def _deg_to_rad(deg: float) -> float:
        return deg * math.pi / 180.0

    @staticmethod
    def _latlon_to_xy_m(lat: float, lon: float, ref_lat: float) -> Tuple[float, float]:
        """
        Convert lat/lon to local x,y in metres using a simple equirectangular approximation.
        This is good enough for short legs (tens of km).
        """
        lat_r = BridgeEngine._deg_to_rad(lat)
        lon_r = BridgeEngine._deg_to_rad(lon)
        ref_lat_r = BridgeEngine._deg_to_rad(ref_lat)

        x = EARTH_RADIUS_M * lon_r * math.cos(ref_lat_r)
        y = EARTH_RADIUS_M * lat_r
        return x, y

    @staticmethod
    def _point_to_segment_distance_m(
        px: float,
        py: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> float:
        """
        Euclidean distance from point P(px,py) to segment A(x1,y1) – B(x2,y2)
        in metres (in local x,y coordinates).
        """
        dx = x2 - x1
        dy = y2 - y1

        if dx == 0 and dy == 0:
            # A and B are the same point
            return math.hypot(px - x1, py - y1)

        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))

        proj_x = x1 + t * dx
        proj_y = y1 + t * dy

        return math.hypot(px - proj_x, py - proj_y)

    # ---------------- public API ---------------- #

    def check_leg(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        vehicle_height_m: float,
    ) -> BridgeCheckResult:
        """
        Check a leg for low-bridge issues.

        We approximate the driven path as a straight line between start and end
        and look for bridges within search_radius_m of that line.

        :param start_lat: start point latitude
        :param start_lon: start point longitude
        :param end_lat: end point latitude
        :param end_lon: end point longitude
        :param vehicle_height_m: running height of the vehicle in metres

        :returns: BridgeCheckResult
        """
        if not self.bridges:
            return BridgeCheckResult(
                has_conflict=False,
                near_height_limit=False,
                nearest_bridge=None,
                nearest_distance_m=None,
            )

        vehicle_height_m = float(vehicle_height_m)
        ref_lat = (start_lat + end_lat) / 2.0

        # Convert endpoints to local x,y in metres
        x1, y1 = self._latlon_to_xy_m(start_lat, start_lon, ref_lat)
        x2, y2 = self._latlon_to_xy_m(end_lat, end_lon, ref_lat)

        has_conflict = False
        near_height_limit = False
        nearest_bridge: Optional[Bridge] = None
        nearest_distance_m: Optional[float] = None

        for b in self.bridges:
            bx, by = self._latlon_to_xy_m(b.lat, b.lon, ref_lat)
            dist_m = self._point_to_segment_distance_m(bx, by, x1, y1, x2, y2)

            # Too far from the leg
            if dist_m > self.search_radius_m:
                continue

            # Height logic
            if b.height_m < vehicle_height_m + self.conflict_clearance_m:
                has_conflict = True

            if b.height_m < vehicle_height_m + self.near_clearance_m:
                near_height_limit = True

            # Track nearest relevant bridge
            if nearest_distance_m is None or dist_m < nearest_distance_m:
                nearest_distance_m = dist_m
                nearest_bridge = b

        return BridgeCheckResult(
            has_conflict=has_conflict,
            near_height_limit=near_height_limit,
            nearest_bridge=nearest_bridge,
            nearest_distance_m=nearest_distance_m,
        )