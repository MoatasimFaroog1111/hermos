"""Immutable per-project research configuration."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    frequency: Literal["daily", "hourly"]
    horizon: int = Field(ge=1)
    trials: int = Field(default=8, ge=0, le=8)
    seed: int = 20261019
    holdout_fraction: float = .2
    minimum_samples: int = 500

    @model_validator(mode="after")
    def supported_horizons(self):
        allowed = (1, 5) if self.frequency == "daily" else (1, 4, 24)
        if self.horizon not in allowed or self.holdout_fraction != .2:
            raise ValueError("unsupported horizon or holdout policy")
        return self
