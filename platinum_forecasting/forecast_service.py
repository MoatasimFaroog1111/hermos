"""Local typed forecast API, gated by operator-owned registry and provider.

No network listener, trading, pickle loading, or automatic model promotion.
The provider must verify exchange calendar and completed-bar semantics.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .features import build_features


@dataclass(frozen=True)
class DataSnapshot:
    bars: pd.DataFrame
    information_cutoff: datetime
    target_timestamp: datetime
    complete: bool
    calendar_verified: bool


class LinearArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["linear_return", "linear_price"]
    features: list[str]
    coefficients: list[float]
    intercept: float

    @model_validator(mode="after")
    def valid_weights(self):
        if not self.features or len(self.features) != len(self.coefficients) or len(set(self.features)) != len(self.features):
            raise ValueError("invalid feature schema")
        if not np.isfinite([*self.coefficients, self.intercept]).all():
            raise ValueError("nonfinite coefficients")
        return self


class Forecast(BaseModel):
    schema_version: Literal["1"] = "1"
    instrument: Literal["PL=F futures"] = "PL=F futures"
    unit: Literal["USD/troy_ounce"] = "USD/troy_ounce"
    frequency: Literal["daily", "hourly"]
    horizon_bars: int
    model_id: str
    reference_price: float = Field(gt=0)
    predicted_price: float = Field(gt=0)
    predicted_change: float
    direction: Literal["up", "down", "flat"]
    lower_price: float
    upper_price: float
    empirical_interval_coverage: float
    issued_at: datetime
    information_cutoff: datetime
    last_price_timestamp: datetime
    target_timestamp: datetime
    data_quality: Literal["validated_completed_bars"] = "validated_completed_bars"


class ForecastService:
    def __init__(self, registry_root: Path, provider: Callable[[], DataSnapshot]):
        self.registry_root = registry_root.resolve()
        self.provider = provider

    def forecast(self, frequency: str, horizon: int, now: datetime) -> Forecast:
        if now.tzinfo is None:
            raise ValueError("timezone-aware issuance time required")
        manifest = json.loads((self.registry_root / "active.json").read_text(encoding="utf-8"))
        if (manifest.get("promotion_status") != "approved" or not manifest.get("quantitative_pass")
                or not manifest.get("data_provenance_verified")):
            raise ValueError("model not approved for production")
        if manifest.get("frequency") != frequency or manifest.get("horizon") != horizon:
            raise ValueError("frequency or horizon does not match registry")
        relative_path = Path(manifest["artifact"])
        path = (self.registry_root / relative_path).resolve()
        if relative_path.is_absolute() or path.parent != self.registry_root:
            raise ValueError("artifact outside trusted registry")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest["artifact_sha256"]:
            raise ValueError("artifact checksum mismatch")
        artifact = LinearArtifact.model_validate_json(data)
        snapshot = self.provider()
        if not snapshot.complete or not snapshot.calendar_verified:
            raise ValueError("incomplete bars or unverified calendar")
        cutoff, target = snapshot.information_cutoff, snapshot.target_timestamp
        if cutoff.tzinfo is None or target.tzinfo is None:
            raise ValueError("timezone-aware provider timestamps required")
        age = now-cutoff
        if age < timedelta(0) or age > (timedelta(days=4) if frequency == "daily" else timedelta(hours=2)):
            raise ValueError("stale or future information cutoff")
        if target <= now or target <= cutoff:
            raise ValueError("target must follow forecast origin and issuance")
        bars = snapshot.bars
        if (bars.empty or not bars.timestamp.is_monotonic_increasing or bars.timestamp.duplicated().any()
                or bars.timestamp.iloc[-1].to_pydatetime() > cutoff):
            raise ValueError("invalid provider ordering or cutoff")
        last_age = now-bars.timestamp.iloc[-1].to_pydatetime()
        if last_age < timedelta(0) or last_age > (timedelta(days=4) if frequency == "daily" else timedelta(hours=2)):
            raise ValueError("stale last price")
        bars = bars.copy()
        delta = bars.timestamp.diff()
        breaks = delta.ne(pd.Timedelta(hours=1)) if frequency == "hourly" else delta.gt(pd.Timedelta(days=4))
        bars["segment"] = breaks.cumsum().astype(int)
        numeric = bars[["open", "high", "low", "close", "volume"]]
        if (not np.isfinite(numeric).all().all() or not numeric[["open", "high", "low", "close"]].gt(0).all().all()
                or numeric.volume.lt(0).any() or (bars.high < bars[["open", "close", "low"]].max(axis=1)).any()
                or (bars.low > bars[["open", "close", "high"]].min(axis=1)).any()):
            raise ValueError("invalid provider prices")
        features = build_features(bars, frequency).add_prefix("feature__")
        row = features.iloc[-1].reindex(artifact.features).to_numpy(float)
        if not np.isfinite(row).all():
            raise ValueError("insufficient continuous history or feature schema mismatch")
        value = float(row @ np.asarray(artifact.coefficients) + artifact.intercept)
        reference = float(bars.close.iloc[-1])
        predicted = reference*np.exp(value) if artifact.kind == "linear_return" else value
        radius_fraction = float(manifest["interval_relative_radius"])
        empirical_coverage = float(manifest["empirical_interval_coverage"])
        if not np.isfinite([predicted, radius_fraction, empirical_coverage]).all() or not 0 < radius_fraction < 1 or not .85 <= empirical_coverage <= 1:
            raise ValueError("invalid prediction interval calibration")
        radius = reference*radius_fraction
        if predicted-radius <= 0:
            raise ValueError("nonpositive forecast interval")
        change = predicted-reference
        return Forecast(frequency=frequency, horizon_bars=horizon, model_id=manifest["model_id"],
                        reference_price=reference, predicted_price=predicted, predicted_change=change,
                        direction="up" if change>0 else "down" if change<0 else "flat",
                        lower_price=predicted-radius, upper_price=predicted+radius,
                        empirical_interval_coverage=empirical_coverage, issued_at=now,
                        information_cutoff=cutoff, last_price_timestamp=bars.timestamp.iloc[-1].to_pydatetime(),
                        target_timestamp=target)
