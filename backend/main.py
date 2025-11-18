# main.py

import math
from typing import List, Tuple

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bridge_engine import BridgeEngine

# -------- CONFIG -------- #

USER_AGENT = "RouteSafeAI/0.1 (contact: example@example.com)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"

app = FastAPI(title="RouteSafe AI", version="0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chrisburley01.github.io",
        "https://chrisburley01.github.io/RouteSafe-AI",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global bridge engine instance
bridge_engine = BridgeEngine(
    csv_path="bridge_heights_clean.csv",
    search_radius_m=300.0,
    conflict_clearance_m=0.