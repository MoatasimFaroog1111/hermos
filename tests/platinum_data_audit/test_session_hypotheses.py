import pytest

pytest.importorskip("pandas", reason="optional platinum audit dependencies")
import pandas as pd

from scripts.platinum_data_audit.session_hypotheses import classify_hourly_intervals, daily_gap_diagnostics, prospective_policy


def timestamps(values):
    return pd.Series(pd.to_datetime(values, utc=True, format="mixed"))


def test_regular_maintenance_is_hypothesis_not_confirmed_missing_data():
    report, intervals = classify_hourly_intervals(timestamps(["2025-01-06T21:00Z", "2025-01-06T23:00Z"]))
    assert intervals.iloc[0]["classification"] == "maintenance_template_consistent_unverified"
    assert report["calendar_verified"] is False
    assert intervals.iloc[0]["open_grid_candidates"] == 0


@pytest.mark.parametrize("left,right,hours", [
    ("2025-03-07T21:00Z", "2025-03-09T22:00Z",49),
    ("2025-10-31T20:00Z", "2025-11-02T23:00Z",51),
    ("2025-01-03T21:00Z", "2025-01-05T23:00Z",50),
])
def test_weekend_template_uses_chicago_dst(left, right, hours):
    _, intervals = classify_hourly_intervals(timestamps([left, right]))
    assert intervals.iloc[0]["elapsed_hours"] == hours
    assert intervals.iloc[0]["classification"] == "weekend_template_consistent_unverified"
    assert intervals.iloc[0]["open_grid_candidates"] == 0


def test_gap_inside_regular_hours_remains_unexplained():
    _, intervals = classify_hourly_intervals(timestamps(["2025-01-07T15:00Z", "2025-01-07T18:00Z"]))
    assert intervals.iloc[0]["classification"] == "unexplained_requires_holiday_or_provider_evidence"
    assert intervals.iloc[0]["open_grid_candidates"] == 2


def test_half_hour_anchored_one_hour_bars_are_not_deleted():
    raw = timestamps(["2024-11-29T14:30Z", "2024-11-29T15:30Z", "2024-11-29T16:30Z"])
    before = raw.copy(deep=True)
    report, intervals = classify_hourly_intervals(raw)
    assert report["half_hour_anchor_records"] == 3
    assert (intervals.classification == "one_hour_half_hour_anchor").all()
    pd.testing.assert_series_equal(raw, before)


def test_intrabar_quote_snapshot_does_not_count_as_completed_bar():
    report, intervals = classify_hourly_intervals(timestamps(["2026-10-19T12:00Z", "2026-10-19T12:32:10Z"]))
    assert report["off_minute_grid_records"] == 1
    assert intervals.iloc[0]["classification"] == "subhour_transition_completion_unknown"


def test_duplicates_are_rejected_before_gap_analysis():
    with pytest.raises(ValueError, match="unique"):
        classify_hourly_intervals(timestamps(["2025-01-01T00:00Z", "2025-01-01T00:00Z"]))


def test_seconds_offset_is_not_labeled_as_half_hour_anchor():
    report, intervals = classify_hourly_intervals(timestamps(["2025-01-01T12:30:10Z", "2025-01-01T13:30:10Z"]))
    assert report["half_hour_anchor_records"] == 0
    assert intervals.iloc[0]["classification"] == "one_hour_other_anchor_unverified"


def test_daily_weekday_count_is_not_claimed_as_missing_sessions():
    report, intervals = daily_gap_diagnostics(timestamps(["2024-12-24", "2024-12-27"]))
    assert intervals.iloc[0]["weekday_candidates"] == 2
    assert report["confirmed_missing_sessions"] is None


def test_unseen_cutoff_must_follow_all_inspected_data_and_freeze_time():
    plan = prospective_policy(pd.Timestamp("2026-10-19T12:32:10Z"), pd.Timestamp("2026-10-20T03:00Z"))
    assert plan["new_holdout_after_exclusive"] == "2026-10-20T03:00:00+00:00"
    assert plan["status"] == "awaiting_new_unseen_completed_observations"
    assert not plan["existing_workbook_eligible_for_new_final_test"]
