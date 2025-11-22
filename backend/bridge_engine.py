# ===========================
# Bridge Engine
# ===========================
#
# Loads low-bridge data from CSV and checks a route geometry
# (list of [lon, lat] points) for nearby low bridges.
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
        near_clear