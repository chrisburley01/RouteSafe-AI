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
    Loads low-bridge data and checks a leg (start_lat/lon -> end_lat/lon)
    for low-bridge issues, given vehicle height.
    """

    def __init__(
        self,
        csv_path: str = "bridge_heights_clean.csv",
        search_radius_m: float = 300.0,
        conflict_clearance_m: float = 0.0,
        near_clearance_m: float = 0.25,
    ):
        self.bridges: List[Bridge] = []
        self.search_radius_m = search_radius_m
        self.conflict_clearance_m = conflict_clearance_m
        self.near_clearance_m = near_clearance_m

        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            # NEVER crash the API if the CSV is missing/bad
            print(f"[BridgeEngine] Failed to load {csv_path}: {e}")
            return

        # Try to detect likely column names automatically
        def find_col(keywords) -> Optional[str]:
            if isinstance(keywords, str):
                keywords_local = [keywords]
            else:
                keywords_local = keywords

            for col in df.columns:
                low = col.lower()
                if all(k in low for k in keywords_local):
                    return col
            return None

        lat_col = find_col("lat")
        lon_col = find_col("lon")
        # e.g. "height_m", "height (m)", "bridge_height_m", etc.
        height_col = find_col(["height", "m"])

        # Some CSVs use ft/feet – we keep it as a string if present
        height_ft_col = find_col(["height", "ft"])

        bridge_id_col = find_col("bridge") or find_col("id")
        name_col = find_col("name")
        os_ref_col = find_col("grid")

        if not lat_col or not lon_col:
            print(
                "[BridgeEngine] No latitude/longitude columns detected in CSV; "
                "bridge checks will be disabled."
            )
            return

        # Clean numeric columns
        df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
        df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")

        if height_col:
            df[height_col] = pd.to_numeric(df[height_col], errors="coerce")

        df = df.dropna(subset=[lat_col, lon_col])

        for idx, row in df.iterrows():
            lat_val = row[lat_col]
            lon_val = row[lon_col]

            if pd.isna(lat_val) or pd.isna(lon_val):
                continue

            height_m_val: Optional[float] = None
            if height_col and not pd.isna(row.get(height_col)):
                height_m_val = float(row[height_col])

            bridge = Bridge(
                bridge_id=str(row.get(bridge_id_col, idx)),
                name=str(row.get(name_col, "")),
                os_grid_ref=str(row.get(os_ref_col, "")),
                height_m=height_m_val,
                height_ft=str(row.get(height_ft_col, "")) if height_ft_col else "",
                lat=float(lat_val),
                lon=float(lon_val),
            )
            self.bridges.append(bridge)

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
        Returns flags + nearest relevant bridge.
        """
        if not self.bridges:
            # Fail-safe: no data → never block, never crash
            return BridgeCheckResult(False, False, None, None)

        ref_lat = (start_lat + end_lat) / 2.0

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
                # Hard conflict = vehicle as tall or taller than bridge (minus tiny buffer)
                if vehicle_height_m + self.conflict_clearance_m > bridge.height_m:
                    has_conflict = True

                # Near limit if within near_clearance_m of bridge height
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
