# telemetry_schema.py
from pydantic import BaseModel, Field
from typing import Optional

class TelemetryPacket(BaseModel):
    driver_id: str
    timestamp_ms: int = Field(..., ge=0)
    lap: int = Field(..., ge=0)
    lap_progress: float = Field(..., ge=0.0, le=1.0)
    speed_mps: float = Field(..., ge=0.0)
    position_x: float
    position_y: float
    yaw: float
    # sector 1..3 or None
    sector: Optional[int] = Field(None, ge=1, le=3)
    throttle_pct: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    brake_pct: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    tyre_temp: Optional[float] = Field(0.0, ge=0.0)
    battery_pct: Optional[float] = Field(None, ge=0.0, le=100.0)

    class Config:
        extra = "forbid"
