# bridge_engine.py

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

EARTH_RADIUS_M = 6371000.0  # metres


@dataclass
class Bridge:
    bridge_id: str
    name: str
    os_grid_ref: str
    height_m: Optional[float]
    height_ft: str
    lat: float
    lon: float


@dataclass
class BridgeCheckResult:
    has_conflict: bool
    near_height_limit: bool
    nearest_bridge: Optional[Bridge]
    nearest_distance_m: Optional[float]


class BridgeEngine:
    """
    Loads low-bridge data and can check a single leg
    against nearby bridges, considering vehicle height.
    """

    def __init__(
        self,
        csv_path: str,
        search_radius_m: float = 300.0,
        conflict_clearance_m: float = 0.0,
        near_clearance_m: float = 0.25,
    ):
        """
        :param csv_path: path to bridge_heights_clean.csv
        :param search_radius_m: only consider bridges within this distance of leg
        :param conflict_clearance_m: if vehicle_height_m + this > bridge.height_m => conflict
        :param near_clearance_m: if vehicle_height_m + this > bridge.height_m => near_height_limit
        """
        self.bridges: List[Bridge] = []
        self.search_radius_m = search_radius_m
        self.conflict_clearance_m = conflict_clearance_m
        self.near_clearance_m = near_clearance_m

        df = pd.read_csv(csv_path)

        # Normalise column names from the cleaned CSV
        df = df.rename(
            columns={
                "BRIDGE DATA": "bridge_id",
                "Unnamed: 4": "bridge_name",
                "Unnamed: 3": "os_grid_ref",
            }
        )

        df["height_m"] = pd.to_numeric(df["height_m"], errors="coerce")
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")

        # Only keep rows with coordinates
        df = df.dropna(subset=["lat", "lon"])

        for _, row in df.iterrows():
            self.bridges.append(
                Bridge(
                    bridge_id=str(row.get("bridge_id", "")),
                    name=str(row.get("bridge_name", "")),
                    os_grid_ref=str(row.get("os_grid_ref", "")),
                    height_m=row.get("height_m"),
                    height_ft=str(row.get("height_ft", "")),
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                )
            )

        print(f"[BridgeEngine] Loaded {len(self.bridges)} bridges with coordinates.")

    # ---------- geometry helpers ---------- #

    @staticmethod
    def _deg_to_rad(deg: float) -> float:
        return deg * math.pi / 180.0

    @staticmethod
    def _latlon_to_xy_m(lat: float, lon: float, ref_lat: float) -> Tuple[float, float]:
        """
        Convert lat/lon to local x,y in metres using equirectangular approximation,
        good enough for distances < ~50km.
        """
        lat_r = BridgeEngine._deg_to_rad(lat)
        lon_r = BridgeEngine._deg_to_rad(lon)
        ref_lat_r = BridgeEngine._deg_to_rad(ref_lat)

        x = EARTH_RADIUS_M * lon_r * math.cos(ref_lat_r)
        y = EARTH_RADIUS_M * lat_r
        return x, y

    @staticmethod
    def _point_to_segment_distance_m(
        px: float, py: float, x1: float, y1: float, x2: float, y2: float
    ) -> float:
        """
        Euclidean distance from point P to segment AB in metres.
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

    # ---------- public API ---------- #

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
        """
        if not self.bridges:
            return BridgeCheckResult(False, False, None, None)

        ref_lat = (start_lat + end_lat) / 2.0

        # Convert leg endpoints to x,y
        x1, y1 = self._latlon_to_xy_m(start_lat, start_lon, ref_lat)
        x2, y2 = self._latlon_to_xy_m(end_lat, end_lon, ref_lat)

        nearest_bridge: Optional[Bridge] = None
        nearest_dist_m: Optional[float] = None
        has_conflict = False
        near_height_limit = False

        for bridge in self.bridges:
            bx, by = self._latlon_to_xy_m(bridge.lat, bridge.lon, ref_lat)
            dist_m = self._point_to_segment_distance_m(bx, by, x1, y1, x2, y2)

            if dist_m > self.search_radius_m:
                continue

            if bridge.height_m is not None:
                if vehicle_height_m + self.conflict_clearance_m > bridge.height_m:
                    has_conflict = True

                if vehicle_height_m + self.near_clearance_m > bridge.height_m:
                    near_height_limit = True

            if nearest_dist_m is None or dist_m < nearest_dist_m:
                nearest_dist_m = dist_m
                nearest_bridge = bridge

        return BridgeCheckResult(
            has_conflict=has_conflict,
            near_height_limit=near_height_limit,
            nearest_bridge=nearest_bridge,
            nearest_distance_m=nearest_dist_m,
        )