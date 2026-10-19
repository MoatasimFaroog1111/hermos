# Data audit — independent datasets

Workbook SHA-256: `85e95ef9f4ed48ad8fc55a890bfc4e08c7b386d2e2adc37bb5646fd2e07d63e1`. Original workbook opened read-only. Sheets: Daily, Hourly, Notes. No original bytes were rewritten.

Workbook Notes identify PL=F front-month platinum futures from Yahoo chart API, native USD/troy ounce; USD/kg is a deterministic conversion. This is not verified spot XPT/USD. Exchange roll rules, settlement versus close, daily bar publication time and licensing are unverified. Workbook statements are provenance claims, not independent vendor certification.

## Daily

Range: 1997-10-29 00:00:00+00:00 through 2026-10-19 00:00:00+00:00.

| Check | Result |
|---|---|
| input_rows | 6586 |
| retained_rows | 6112 |
| invalid_numeric | 0 |
| invalid_ohlc | 473 |
| exact_duplicates | 0 |
| off_grid | 0 |
| incomplete_tail_excluded | 1 |
| zero_volume | 1776 |
| return_spikes_over_15pct | 6 |
| continuity_segments | 278 |

Nulls: `{'timestamp': 0, 'open': 0, 'high': 0, 'low': 0, 'close': 0, 'volume': 0}`. Original timestamps sorted: True.

Interval histogram (all observed intervals; missing bars are not inserted):

| Interval | Count |
|---|---|
| 1 days 00:00:00 | 5144 |
| 3 days 00:00:00 | 1172 |
| 4 days 00:00:00 | 180 |
| 2 days 00:00:00 | 50 |
| 5 days 00:00:00 | 17 |
| 62 days 00:00:00 | 4 |
| 30 days 00:00:00 | 3 |
| 60 days 00:00:00 | 2 |
| 63 days 00:00:00 | 2 |
| 57 days 00:00:00 | 1 |
| 51 days 00:00:00 | 1 |
| 78 days 00:00:00 | 1 |
| 52 days 00:00:00 | 1 |
| 27 days 00:00:00 | 1 |
| 18 days 00:00:00 | 1 |
| 13 days 00:00:00 | 1 |
| 29 days 00:00:00 | 1 |
| 26 days 00:00:00 | 1 |
| 21 days 00:00:00 | 1 |
| 61 days 00:00:00 | 1 |

Deterministic cleaning: reject invalid numeric/OHLC rows, normalize timestamps, remove exact duplicates, reject conflicting duplicates, exclude off-grid records and final potentially incomplete on-grid bar. Retain real spikes and zero volume; do not impute prices, backfill, winsorize or synthesize hourly data. Break segments at quarantines. Daily gaps >4 days and every non-one-hour hourly gap break continuity. These are conservative research rules, not validated exchange sessions.

## Hourly

Range: 2024-10-20 22:00:00+00:00 through 2026-10-19 12:32:10+00:00.

| Check | Result |
|---|---|
| input_rows | 11440 |
| retained_rows | 11418 |
| invalid_numeric | 0 |
| invalid_ohlc | 0 |
| exact_duplicates | 0 |
| off_grid | 21 |
| incomplete_tail_excluded | 1 |
| zero_volume | 409 |
| return_spikes_over_15pct | 0 |
| continuity_segments | 517 |

Nulls: `{'timestamp': 0, 'open': 0, 'high': 0, 'low': 0, 'close': 0, 'volume': 0}`. Original timestamps sorted: True.

Interval histogram (all observed intervals; missing bars are not inserted):

| Interval | Count |
|---|---|
| 0 days 01:00:00 | 10917 |
| 0 days 02:00:00 | 392 |
| 2 days 02:00:00 | 84 |
| 0 days 00:30:00 | 5 |
| 1 days 01:00:00 | 5 |
| 2 days 01:00:00 | 3 |
| 2 days 08:00:00 | 3 |
| 0 days 10:30:00 | 3 |
| 2 days 05:00:00 | 2 |
| 2 days 19:00:00 | 2 |
| 1 days 11:00:00 | 2 |
| 1 days 10:30:00 | 2 |
| 1 days 08:00:00 | 2 |
| 3 days 02:00:00 | 2 |
| 0 days 04:00:00 | 2 |
| 0 days 03:00:00 | 2 |
| 2 days 04:00:00 | 2 |
| 3 days 08:00:00 | 2 |
| 2 days 03:00:00 | 1 |
| 2 days 06:00:00 | 1 |
| 0 days 11:00:00 | 1 |
| 2 days 07:00:00 | 1 |
| 0 days 10:00:00 | 1 |
| 2 days 13:00:00 | 1 |
| 0 days 00:32:10 | 1 |

Deterministic cleaning: reject invalid numeric/OHLC rows, normalize timestamps, remove exact duplicates, reject conflicting duplicates, exclude off-grid records and final potentially incomplete on-grid bar. Retain real spikes and zero volume; do not impute prices, backfill, winsorize or synthesize hourly data. Break segments at quarantines. Daily gaps >4 days and every non-one-hour hourly gap break continuity. These are conservative research rules, not validated exchange sessions.

## Limitations and decision

Daily records contain long gaps, including multi-month gaps, and 473 OHLC inconsistencies. They cannot be silently treated as a complete historical series. Hourly off-grid records include half-hour timestamps as well as the trailing 12:32:10 quote; some could reflect shortened sessions, but are excluded until verified. Hourly UTC and Riyadh (+03:00) representations agree for all rows. Daily date labels remain date labels; interpreting midnight UTC as the actual daily information availability time is not justified.

The longest hourly exact-one-hour segment contains 47 bars. Use frequency-specific short hourly features; 24-bar-ahead research has only 11 eligible examples and is blocked. Two calendar years are not evidence of enough independent hourly observations for deep learning. Daily and hourly models share code, never data or learned parameters.

Potential contract-roll discontinuities, sparse/zero volume, unverified quote completeness, vendor revisions and missing sessions prevent production data approval. Historical evaluations are conditional research evidence, not point-in-time-certified market results.
