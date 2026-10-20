"""DST-aware regular-session hypotheses, explicitly not an exchange calendar."""
from __future__ import annotations

import pandas as pd

REGULAR_TEMPLATE = {
    "timezone": "America/Chicago", "open_local": "17:00", "close_local": "16:00",
    "description": "Hypothesis: Sunday-Friday 17:00-to-16:00 CT sessions with maintenance 16:00-17:00; no holidays",
    "verified_by_official_source": False,
}


def _timestamps(values: pd.Series) -> pd.Series:
    result = pd.to_datetime(values, utc=True, errors="raise", format="mixed").reset_index(drop=True)
    if result.isna().any() or result.duplicated().any() or not result.is_monotonic_increasing:
        raise ValueError("timestamps must be present, sorted and unique")
    return result


def _template_open(timestamp: pd.Timestamp) -> bool:
    local = timestamp.tz_convert("America/Chicago")
    if local.dayofweek == 5:
        return False
    if local.dayofweek == 6:
        return local.hour >= 17
    if local.dayofweek == 4:
        return local.hour < 16
    return local.hour < 16 or local.hour >= 17


def classify_hourly_intervals(values: pd.Series) -> tuple[dict, pd.DataFrame]:
    timestamps = _timestamps(values)
    records = []
    for previous, current in zip(timestamps.iloc[:-1], timestamps.iloc[1:]):
        elapsed = (current-previous).total_seconds()/3600
        open_candidates = None
        if elapsed == 1:
            label = "one_hour_regular_anchor" if current == current.floor("h") else "one_hour_half_hour_anchor" if current == current.floor("h")+pd.Timedelta(minutes=30) else "one_hour_other_anchor_unverified"
        elif elapsed < 1:
            label = "subhour_transition_completion_unknown"
        elif previous != previous.floor("h") or current != current.floor("h"):
            label = "irregular_anchor_gap_requires_provider_evidence"
        else:
            interior = pd.date_range(previous+pd.Timedelta(hours=1), current-pd.Timedelta(hours=1), freq="h")
            open_candidates = sum(_template_open(t) for t in interior)
            if open_candidates:
                label = "unexplained_requires_holiday_or_provider_evidence"
            elif any(t.tz_convert("America/Chicago").dayofweek == 5 for t in interior):
                label = "weekend_template_consistent_unverified"
            else:
                label = "maintenance_template_consistent_unverified"
        records.append({"previous": previous, "current": current, "elapsed_hours": elapsed,
                        "previous_chicago": previous.tz_convert("America/Chicago").isoformat(),
                        "current_chicago": current.tz_convert("America/Chicago").isoformat(),
                        "classification": label, "open_grid_candidates": open_candidates})
    columns = ["previous", "current", "elapsed_hours", "previous_chicago", "current_chicago", "classification", "open_grid_candidates"]
    intervals = pd.DataFrame(records, columns=columns)
    summary = {"records": len(timestamps), "intervals": len(intervals),
               "calendar_verified": False, "regular_template": REGULAR_TEMPLATE,
               "classification_counts": {str(k): int(v) for k,v in intervals.classification.value_counts().items()},
               "half_hour_anchor_records": int(((timestamps.dt.minute==30)&(timestamps.dt.second==0)).sum()),
               "off_minute_grid_records": int((timestamps != timestamps.dt.floor("min")).sum()),
               "confirmed_missing_bars": None,
               "open_grid_candidates_total_not_confirmed_missing": int(intervals.open_grid_candidates.sum())}
    return summary, intervals


def daily_gap_diagnostics(values: pd.Series) -> tuple[dict, pd.DataFrame]:
    timestamps = _timestamps(values)
    records = []
    for previous, current in zip(timestamps.iloc[:-1], timestamps.iloc[1:]):
        elapsed = (current.normalize()-previous.normalize()).days
        if elapsed <= 1:
            continue
        weekday_candidates = len(pd.bdate_range(previous.normalize()+pd.Timedelta(days=1), current.normalize()-pd.Timedelta(days=1)))
        records.append({"previous": previous, "current": current, "calendar_days": elapsed,
                        "weekday_candidates": weekday_candidates,
                        "classification": "weekday_template_weekend_only_unverified" if not weekday_candidates else "requires_holiday_or_provider_evidence"})
    intervals = pd.DataFrame(records, columns=["previous", "current", "calendar_days", "weekday_candidates", "classification"])
    summary = {"records": len(timestamps), "nonconsecutive_dates": len(intervals),
               "gaps_over_seven_calendar_days": int(intervals.calendar_days.gt(7).sum()),
               "maximum_calendar_days": int(intervals.calendar_days.max()) if len(intervals) else 0,
               "weekday_candidates_not_confirmed_missing": int(intervals.weekday_candidates.sum()),
               "confirmed_missing_sessions": None, "calendar_verified": False}
    return summary, intervals


def prospective_policy(last_inspected_timestamp: pd.Timestamp, frozen_at: pd.Timestamp) -> dict:
    last_inspected_timestamp = pd.Timestamp(last_inspected_timestamp)
    frozen_at = pd.Timestamp(frozen_at)
    if last_inspected_timestamp.tzinfo is None or frozen_at.tzinfo is None:
        raise ValueError("timezone-aware cutoff required")
    cutoff = max(last_inspected_timestamp.tz_convert("UTC"), frozen_at.tz_convert("UTC"))
    return {"status": "awaiting_new_unseen_completed_observations",
            "new_holdout_after_exclusive": cutoff.isoformat(),
            "existing_workbook_eligible_for_new_final_test": False,
            "minimum_holdout_observations_per_horizon": 200,
            "completion_requirement": "bar availability and completion after cutoff; targets must also be after cutoff",
            "promotion_allowed": False,
            "release_requirements": ["authoritative session and holiday calendar", "verified Yahoo or replacement provider publication/roll semantics", "separate temporal development and sealed final data", "preregistered model, feature and quantitative gates", "human production approval"]}
