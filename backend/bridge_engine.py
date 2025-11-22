# backend/bridge_engine.py
#
# Uses cleaned UK low-bridge data (lat, lon, height_m)
# to check a straight-line leg (start → end) for low-bridge risks.

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
    conflict_bridges: List[Bridge]
    near_bridges: List[Bridge]


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
        self.csv_path = csv_path
        self.search_radius_m = search_radius_m
        self.conflict_clearance_m = conflict_clearance_m
        self.near_clearance_m = near_clearance_m

        df = pd.read_csv(csv_path)
        for col in ["lat", "lon", "height_m"]:
            if col not in df.columns:
                raise ValueError(f"CSV is missing required column '{col}'")

        self.bridges: List[Bridge] = [
            Bridge(float(row["lat"]), float(row["lon"]), float(row["height_m"]))
            for _, row in df.iterrows()
        ]

    @staticmethod
    def _haversine_distance(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
            dlambda / 2.0
        ) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return EARTH_RADIUS_M * c

    @classmethod
    def _point_to_segment_distance(
        cls,
        lat_p: float,
        lon_p: float,
        lat_a: float,
        lon_a: float,
        lat_b: float,
        lon_b: float,
    ) -> float:
        def to_xy(lat_ref: float, lon_ref: float, lat: float, lon: float) -> Tuple[float, float]:
            x = math.radians(lon - lon_ref) * EARTH_RADIUS_M * math.cos(math.radians(lat_ref))
            y = math.radians(lat - lat_ref) * EARTH_RADIUS_M
            return x, y

        ax, ay = to_xy(lat_a, lon_a, lat_a, lon_a)
        bx, by = to_xy(lat_a, lon_a, lat_b, lon_b)
        px, py = to_xy(lat_a, lon_a, lat_p, lon_p)

        abx = bx - ax
        aby = by - ay
        apx = px - ax
        apy = py - ay

        ab_len_sq = abx * abx + aby * aby
        if ab_len_sq == 0:
            return math.hypot(apx, apy)

        t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_len_sq))
        closest_x = ax + t * abx
        closest_y = ay + t * aby

        return math.hypot(px - closest_x, py - closest_y)

    def check_leg(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        vehicle_height_m: float,
    ) -> BridgeCheckResult:
        nearest_bridge: Optional[Bridge] = None
        nearest_distance_m: Optional[float] = None
        conflict_bridges: List[Bridge] = []
        near_bridges: List[Bridge] = []

        for bridge in self.bridges:
            d = self._point_to_segment_distance(
                bridge.lat,
                bridge.lon,
                start_lat,
                start_lon,
                end_lat,
                end_lon,
            )

            if d > self.search_radius_m:
                continue

            if nearest_distance_m is None or d < nearest_distance_m:
                nearest_bridge = bridge
                nearest_distance_m = d

            height_diff = vehicle_height_m - bridge.height_m

            if height_diff > self.conflict_clearance_m:
                conflict_bridges.append(bridge)
            elif height_diff > -self.near_clearance_m:
                near_bridges.append(bridge)

        has_conflict = len(conflict_bridges) > 0
        near_height_limit = not has_conflict and len(near_bridges) > 0

        return BridgeCheckResult(
            has_conflict=has_conflict,
            near_height_limit=near_height_limit,
            nearest_bridge=nearest_bridge,
            nearest_distance_m=nearest_distance_m,
            conflict_bridges=conflict_bridges,
            near_bridges=near_bridges,
        )