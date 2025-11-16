# sim_config_api.py
import os
import json
from datetime import datetime
from typing import Dict, Optional, Any
from fastapi import APIRouter, FastAPI, HTTPException, Body, Query
from pydantic import BaseModel, Field, validator

# Put this file in the same folder as intent_service.py and import the router into your main app:
# from sim_config_api import router as sim_config_router
# app.include_router(sim_config_router, prefix="/api/sim")

router = APIRouter()
REPLAY_DIR = "replays"
os.makedirs(REPLAY_DIR, exist_ok=True)

# --- Pydantic models for validation ---


class DriverConfig(BaseModel):
    name: Optional[str] = None
    team: Optional[str] = None
    base_speed: Optional[float] = Field(None, ge=0.0)
    aggression: Optional[float] = Field(None, ge=0.0, le=1.0)
    # Engine / energy / fuel fields are optional and scenario-specific
    fuel_load: Optional[float] = Field(None, ge=0.0)
    battery_capacity_kwh: Optional[float] = Field(None, ge=0.0)
    start_charge_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    regen_profile: Optional[str] = None
    # generic storage for any extras
    extras: Optional[Dict[str, Any]] = None


class AdvancedOptions(BaseModel):
    random_seed: Optional[int] = None
    weather_change: bool = False
    weather_pattern: Optional[str] = "static"
    event_intensity: Optional[str] = Field("medium")
    enable_crashes: bool = True
    enable_mechanical_failures: bool = True
    enable_energy_management: bool = True
    # F1/FE specifics (optional)
    battery_capacity_kwh: Optional[float] = None
    regen_efficiency: Optional[float] = None
    attack_mode_enabled: Optional[bool] = False
    attack_mode_duration_sec: Optional[int] = None
    attack_mode_activations: Optional[int] = None

    @validator("event_intensity")
    def check_event_intensity(cls, v):
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            raise ValueError(f"event_intensity must be one of {allowed}")
        return v


class SimConfig(BaseModel):
    race_type: Optional[str] = Field("generic")  # FE, F1 or generic
    run_name: Optional[str] = None
    track: str
    num_cars: int = Field(..., ge=1, le=40)
    total_laps: Optional[int] = Field(None, ge=1)
    duration_seconds: Optional[int] = Field(None, ge=1)
    safety_mode: Optional[str] = Field("none")
    starting_weather: Optional[str] = Field("sunny")
    advanced: Optional[AdvancedOptions] = AdvancedOptions()
    drivers: Optional[Dict[str, DriverConfig]] = {}

    @validator("starting_weather")
    def valid_weather(cls, v):
        allowed = {"sunny", "overcast", "light_rain", "heavy_rain", "windy"}
        if v not in allowed:
            raise ValueError(f"starting_weather must be one of {allowed}")
        return v

    @validator("safety_mode")
    def valid_safety(cls, v):
        allowed = {"none", "strict", "always_on", "disabled"}
        if v not in allowed:
            raise ValueError(f"safety_mode must be one of {allowed}")
        return v


# --- Shared state (simple globals to integrate with your existing intent_service) ---
# NOTE: intent_service.py already has current_run_id and current_replay in its global scope.
# If you want to share the same objects, import them instead of re-defining.
# For quick integration, you can update these globals from here and intent_service should read them.

current_run_id: Optional[str] = None
current_replay: Optional[Dict[str, Any]] = None

def save_config_file(run_id: str, cfg: Dict[str, Any]) -> str:
    path = os.path.join(REPLAY_DIR, f"{run_id}_config.json")
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    return path

def load_config_file(run_id: str) -> Dict[str, Any]:
    path = os.path.join(REPLAY_DIR, f"{run_id}_config.json")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r") as f:
        return json.load(f)

def mk_run_id(name: Optional[str] = None) -> str:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    if name:
        safe = name.replace(" ", "_")
        return f"{safe}_{ts}"
    return f"run_{ts}"


# --- API endpoints ---


@router.post("/start", summary="Start a simulation run with the supplied configuration")
def start_simulation(config: SimConfig = Body(...), force: bool = Query(False, description="Force start even if a run is active")):
    """
    Validate and save the simulation configuration. This endpoint initializes a run_id and
    creates a replay skeleton where telemetry and intent predictions will be appended.
    If force=True, the current run will be replaced.
    """
    global current_run_id, current_replay

    # create run_id
    run_id = mk_run_id(config.run_name)

    # prepare plain dict to save (use by_alias False to keep keys clean)
    cfg_dict = config.dict()

    # add run metadata
    cfg_dict["_meta"] = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "run_id": run_id
    }

    # Save config file
    save_config_file(run_id, cfg_dict)

    # initialize replay skeleton for this run (so intent_service can append to it)
    if current_run_id and not force:
        raise HTTPException(status_code=409, detail=f"Run already active: {current_run_id}. Use ?force=true to override.")
    current_run_id = run_id
    current_replay = {
        "run_id": run_id,
        "config": cfg_dict,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "telemetry": [],
        "intent_predictions": [],
        "events": []
    }

    # also write initial skeleton to disk immediately
    replay_path = os.path.join(REPLAY_DIR, f"{run_id}.json")
    with open(replay_path, "w") as f:
        json.dump(current_replay, f, indent=2)

    return {"ok": True, "run_id": run_id, "replay_path": replay_path}


@router.get("/config/{run_id}", summary="Fetch saved simulation config for a run")
def get_config(run_id: str):
    try:
        cfg = load_config_file(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config not found")
    return cfg


@router.get("/current", summary="Return current active run info")
def get_current():
    return {"run_id": current_run_id, "current_replay_exists": bool(current_replay), "config": current_replay.get("config") if current_replay else None}


@router.get("/list", summary="List saved simulation config run IDs")
def list_runs():
    files = os.listdir(REPLAY_DIR)
    runs = []
    for f in files:
        if f.endswith("_config.json"):
            runs.append(f.replace("_config.json", ""))
    runs.sort(reverse=True)
    return {"runs": runs}
