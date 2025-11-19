# bridge_engine.py
#
# Core logic for checking a route against low bridges.

from typing import List, Tuple, Dict
import math
import pandas as pd


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two points on Earth (in metres).
    """
    R = 6371000.0  # metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def feet_inches_to_meters(feet: float, inches: float) -> float:
    """
    Convert a height given in feet + inches to metres.
    """
    total_inches = float(feet) * 12.0 + float(inches)
    return total_inches * 0.0254  # exact inch→metres factor


class BridgeEngine:
    """
    Loads bridge data and checks a route for low-bridge conflicts.

    CSV expectations (we handle a few variants):

      Option A (recommended, in feet + inches):
        latitude, longitude, height_ft, height_in

      Option B (already in metres):
        latitude, longitude, height_m

      Option C (single height column in metres):
        latitude, longitude, height
    """

    def __init__(
        self,
        csv_path: str = "bridge_heights_clean.csv",
        search_radius_m: float = 300.0,
        conflict_clearance_m: float = 0.0,
        near_clearance_m: float = 0.25,
    ) -> None:
        self.csv_path = csv_path
        self.search_radius_m = float(search_radius_m)
        self.conflict_clearance_m = float(conflict_clearance_m)
        self.near_clearance_m = float(near_clearance_m)

        self.bridges = pd.read_csv(self.csv_path)

        # --- Normalise height into metres ------------------------------------
        if "height_m" in self.bridges.columns:
            # Already in metres; just cast to float
            self.bridges["height_m"] = self.bridges["height_m"].astype(float)

        elif {"height_ft", "height_in"}.issubset(self.bridges.columns):
            # Convert from feet + inches
            self.bridges["height_m"] = self.bridges.apply(
                lambda row: feet_inches_to_meters(row["height_ft"], row["height_in"]),
                axis=1,
            )

        elif "height" in self.bridges.columns:
            # Single column; assume already metres
            self.bridges["height_m"] = self.bridges["height"].astype(float)

        else:
            raise ValueError(
                "bridge_heights_clean.csv must contain either "
                "`height_m`, or (`height_ft` and `height_in`), "
                "or a `height` column in metres."
            )

        # Make sure core columns exist
        required_cols = {"latitude", "longitude", "height_m"}
        missing = required_cols - set(self.bridges.columns)
        if missing:
            raise ValueError(
                f"Bridge CSV is missing required columns: {', '.join(sorted(missing))}"
            )

    # --------------------------------------------------------------------- #
    # Core API
    # --------------------------------------------------------------------- #

    def analyse_route(
        self,
        route_points: List[Tuple[float, float]],
        vehicle_height_m: float,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Check a route against the bridge dataset.

        route_points: list of (lat, lon) pairs representing the route.
        vehicle_height_m: running height of the vehicle in metres.

        Returns:
            conflicts, near_misses

            conflicts   = list of dicts where bridge < vehicle_height_m + conflict_clearance_m
            near_misses = list of dicts where
                          vehicle_height_m + conflict_clearance_m
                          <= bridge < vehicle_height_m + near_clearance_m
        """
        if not route_points:
            return [], []

        vehicle_height_m = float(vehicle_height_m)

        conflicts: List[Dict] = []
        near_misses: List[Dict] = []

        # For each bridge, find the closest route point and evaluate clearance
        for _, row in self.bridges.iterrows():
            b_lat = float(row["latitude"])
            b_lon = float(row["longitude"])
            b_height_m = float(row["height_m"])

            # Nearest point on the route (simple but fine for short legs)
            min_dist = min(
                haversine_m(b_lat, b_lon, r_lat, r_lon)
                for (r_lat, r_lon) in route_points
            )

            if min_dist > self.search_radius_m:
                # Bridge too far from the driven line; ignore
                continue

            # Clearance: how much higher the bridge is than the vehicle
            clearance_m = b_height_m - vehicle_height_m

            # Conflict: bridge is below the vehicle (plus any extra buffer)
            if b_height_m < vehicle_height_m + self.conflict_clearance_m:
                conflicts.append(
                    {
                        "latitude": b_lat,
                        "longitude": b_lon,
                        "height_m": b_height_m,
                        "distance_m": min_dist,
                        "clearance_m": clearance_m,
                    }
                )
            # Near miss: just above vehicle but within the "near" buffer
            elif b_height_m < vehicle_height_m + self.near_clearance_m:
                near_misses.append(
                    {
                        "latitude": b_lat,
                        "longitude": b_lon,
                        "height_m": b_height_m,
                        "distance_m": min_dist,
                        "clearance_m": clearance_m,
                    }
                )

        # Sort by how close they are to the route
        conflicts.sort(key=lambda x: x["distance_m"])
        near_misses.sort(key=lambda x: x["distance_m"])

        return conflicts, near_misses

    # Backwards-compat alias – in case main.py calls this
    def check_route(
        self,
        route_points: List[Tuple[float, float]],
        vehicle_height_m: float,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Wrapper to keep compatibility with older code.
        """
        return self.analyse_route(route_points, vehicle_height_m)