# bridge_engine.py
#
# Uses cleaned Network Rail bridge data (lat, lon, height_m)
# to check a straight-line leg for low-bridge risks.

from dataclasses import dataclass
from typing import Optional, Tuple

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
        :param csv_path: Path to cleaned bridge CSV
        :param search_radius_m: How far from the leg to look for bridges
        :param conflict_clearance_m: clearance <= this -> hard conflict
        :param near_clearance_m: clearance <= this -> near-height warning
        """
        self.csv_path = csv_path
        self.search_radius_m = search_radius_m
        self.conflict_clearance_m = conflict_clearance_m
        self.near_clearance_m = near_clearance_m

        df = pd.read_csv(csv_path)

        # Make sure columns exist
        required_cols = {"lat", "lon", "height_m"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"Bridge CSV missing columns: {missing}")

        self.bridges_df = df[["lat", "lon", "height_m"]].dropna().reset_index(drop=True)

    # ------------------------------------------------------------
    # Basic geo helpers
    # ------------------------------------------------------------
    @staticmethod
    def _to_radians(lat: float, lon: float) -> Tuple[float, float]:
        return math.radians(lat), math.radians(lon)

    @staticmethod
    def haversine_distance_m(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """
        Great-circle distance between two lat/lon points (in metres).
        """
        phi1, lam1 = BridgeEngine._to_radians(lat1, lon1)
        phi2, lam2 = BridgeEngine._to_radians(lat2, lon2)

        dphi = phi2 - phi1
        dlam = lam2 - lam1

        a = (
            math.sin(dphi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return EARTH_RADIUS_M * c

    @staticmethod
    def _latlon_to_xy_m(lat: float, lon: float, ref_lat_rad: float) -> Tuple[float, float]:
        """
        Approximate lat/lon to local x/y in metres using equirectangular projection.
        """
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        x = EARTH_RADIUS_M * (lon_rad) * math.cos(ref_lat_rad)
        y = EARTH_RADIUS_M * (lat_rad)
        return x, y

    @staticmethod
    def _point_to_segment_distance_m(
        px: float, py: float, ax: float, ay: float, bx: float, by: float
    ) -> float:
        """
        Distance from point P to line segment AB in metres (2D).
        """
        vx = bx - ax
        vy = by - ay
        wx = px - ax
        wy = py - ay

        seg_len2 = vx * vx + vy * vy
        if seg_len2 == 0.0:
            # A and B are the same point
            dx = px - ax
            dy = py - ay
            return math.sqrt(dx * dx + dy * dy)

        t = (wx * vx + wy * vy) / seg_len2
        if t < 0.0:
            closest_x, closest_y = ax, ay
        elif t > 1.0:
            closest_x, closest_y = bx, by
        else:
            closest_x = ax + t * vx
            closest_y = ay + t * vy

        dx = px - closest_x
        dy = py - closest_y
        return math.sqrt(dx * dx + dy * dy)

    # ------------------------------------------------------------
    # Main public method
    # ------------------------------------------------------------
    def check_leg(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        vehicle_height_m: float,
    ) -> BridgeCheckResult:
        """
        Check a route leg (start -> end) for low-bridge risk.

        :param start: (lat, lon)
        :param end: (lat, lon)
        :param vehicle_height_m: Full running height of vehicle (metres)
        """
        start_lat, start_lon = start
        end_lat, end_lon = end

        # Rough bounding box filter to keep only nearby bridges
        mid_lat = (start_lat + end_lat) / 2.0
        mid_lon = (start_lon + end_lon) / 2.0
        mid_lat_rad = math.radians(mid_lat)

        # Convert search radius to degrees
        deg_per_m_lat = 1.0 / 111000.0
        deg_per_m_lon = 1.0 / (111000.0 * max(math.cos(mid_lat_rad), 0.1))

        d_lat = self.search_radius_m * deg_per_m_lat
        d_lon = self.search_radius_m * deg_per_m_lon

        lat_min = min(start_lat, end_lat) - d_lat
        lat_max = max(start_lat, end_lat) + d_lat
        lon_min = min(start_lon, end_lon) - d_lon
        lon_max = max(start_lon, end_lon) + d_lon

        candidates = self.bridges_df[
            (self.bridges_df["lat"] >= lat_min)
            & (self.bridges_df["lat"] <= lat_max)
            & (self.bridges_df["lon"] >= lon_min)
            & (self.bridges_df["lon"] <= lon_max)
        ]

        # If no bridges near the corridor, it's trivially safe
        if candidates.empty:
            return BridgeCheckResult(
                has_conflict=False,
                near_height_limit=False,
                nearest_bridge=None,
                nearest_distance_m=None,
            )

        # Convert leg endpoints to local x/y metres
        ax, ay = self._latlon_to_xy_m(start_lat, start_lon, mid_lat_rad)
        bx, by = self._latlon_to_xy_m(end_lat, end_lon, mid_lat_rad)

        has_conflict = False
        near_height_limit = False
        nearest_bridge: Optional[Bridge] = None
        nearest_distance_m: Optional[float] = None

        for _, row in candidates.iterrows():
            b_lat = float(row["lat"])
            b_lon = float(row["lon"])
            b_h = float(row["height_m"])

            px, py = self._latlon_to_xy_m(b_lat, b_lon, mid_lat_rad)

            dist_m = self._point_to_segment_distance_m(px, py, ax, ay, bx, by)

            if dist_m > self.search_radius_m:
                continue  # too far from this leg

            clearance = b_h - vehicle_height_m

            # Track nearest bridge regardless of height
            if nearest_distance_m is None or dist_m < nearest_distance_m:
                nearest_distance_m = dist_m
                nearest_bridge = Bridge(lat=b_lat, lon=b_lon, height_m=b_h)

            # Height checks
            if clearance <= self.conflict_clearance_m:
                has_conflict = True
                near_height_limit = True  # also near by definition
            elif clearance <= self.near_clearance_m:
                near_height_limit = True

        return BridgeCheckResult(
            has_conflict=has_conflict,
            near_height_limit=near_height_limit,
            nearest_bridge=nearest_bridge,
            nearest_distance_m=nearest_distance_m,
        )