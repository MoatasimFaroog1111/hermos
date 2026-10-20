# Platinum source and session audit

Original workbook SHA-256: `85e95ef9f4ed48ad8fc55a890bfc4e08c7b386d2e2adc37bb5646fd2e07d63e1`.
Audit frozen: 2026-10-20T03:57:36.211675+00:00.

This is a new read-only forensic audit, not a new model experiment. Previous final holdouts remain consumed. No original values, feature policies, model choices or old results were changed.

## Daily anomalies

| Check | Count |
|---|---:|
| rows | 6586 |
| invalid_numeric | 0 |
| ohlc_violations | 473 |
| open_outside_range | 61 |
| close_outside_range | 459 |
| inverted_ranges | 4 |
| open_and_close_outside | 47 |
| zero_volume | 1776 |

Disjoint reasons: `{"close_outside_only": 412, "inverted_range": 4, "open_and_close_outside": 43, "open_outside_only": 14, "valid_ohlc": 6113}`.
Violations by year: `{"1999": 32, "2000": 30, "2001": 42, "2002": 42, "2003": 42, "2004": 35, "2005": 44, "2006": 38, "2007": 27, "2008": 29, "2009": 25, "2010": 42, "2011": 45}`.
Violations on/after the start of hourly coverage: 0.

A daily settlement versus intraday range mismatch, historical vendor adjustment or contract stitching could explain some close-outside-range rows. These are hypotheses, not established causes. Inverted high/low ranges cannot be justified by a settlement-only explanation. No prices are clipped, swapped, interpolated or replaced.

## Daily date gaps

`{"calendar_verified": false, "confirmed_missing_sessions": null, "gaps_over_seven_calendar_days": 22, "maximum_calendar_days": 78, "nonconsecutive_dates": 1441, "records": 6586, "weekday_candidates_not_confirmed_missing": 973}`

Weekday counts are candidate labels, not confirmed missing exchange sessions. Holiday schedules and historical source coverage remain necessary.

## Hourly interval evidence

| Classification | Intervals |
|---|---:|
| one_hour_regular_anchor | 10902 |
| maintenance_template_consistent_unverified | 392 |
| weekend_template_consistent_unverified | 88 |
| unexplained_requires_holiday_or_provider_evidence | 31 |
| one_hour_half_hour_anchor | 15 |
| subhour_transition_completion_unknown | 6 |
| irregular_anchor_gap_requires_provider_evidence | 5 |

The regular-session template uses America/Chicago DST rules and assumes a 17:00 opening, 16:00 close, daily maintenance and weekend closure. It is not an authenticated exchange holiday calendar; template-consistent intervals must not be described as verified exchange closures.

Half-hour anchored records: 20; off-minute-grid records: 1.
Consecutive half-hour anchored labels can be exactly one hour apart. They are not automatically invalid or synthetic. Their holiday/session anchoring requires vendor and exchange evidence. The terminal subhour quote does not establish a completed hourly candle.

Hourly numeric/OHLC violations: 0/0.

## Conversion and timestamp checks

USD/kg conversion diagnostics: `{"daily": {"close": {"comparable_rows": 6586, "factor_tested": 32.15074657, "max_absolute_difference": 3.913548425771296e-06, "mismatches": 0, "noncomparable_rows": 0, "status": "checked"}, "high": {"comparable_rows": 6586, "factor_tested": 32.15074657, "max_absolute_difference": 3.913548425771296e-06, "mismatches": 0, "noncomparable_rows": 0, "status": "checked"}, "low": {"comparable_rows": 6586, "factor_tested": 32.15074657, "max_absolute_difference": 3.913548425771296e-06, "mismatches": 0, "noncomparable_rows": 0, "status": "checked"}, "open": {"comparable_rows": 6586, "factor_tested": 32.15074657, "max_absolute_difference": 3.913548425771296e-06, "mismatches": 0, "noncomparable_rows": 0, "status": "checked"}}, "hourly": {"close": {"comparable_rows": 11440, "factor_tested": 32.15074657, "max_absolute_difference": 4.000408807769418e-06, "mismatches": 0, "noncomparable_rows": 0, "status": "checked"}, "high": {"comparable_rows": 11440, "factor_tested": 32.15074657, "max_absolute_difference": 4.0131708374246955e-06, "mismatches": 0, "noncomparable_rows": 0, "status": "checked"}, "low": {"comparable_rows": 11440, "factor_tested": 32.15074657, "max_absolute_difference": 3.9309816202148795e-06, "mismatches": 0, "noncomparable_rows": 0, "status": "checked"}, "open": {"comparable_rows": 11440, "factor_tested": 32.15074657, "max_absolute_difference": 3.998895408585668e-06, "mismatches": 0, "noncomparable_rows": 0, "status": "checked"}}}`.
The conversion-factor check establishes consistency with workbook arithmetic, not the market instrument, its native currency or permission to redistribute prices.
UTC and Asia/Riyadh representations agree for every hourly record. This does not establish daily availability time or settlement publication time.

## Source verification

| Source | Observed outcome | Verified content |
|---|---|---|
| [cme_contract](https://www.cmegroup.com/markets/metals/precious/platinum.contractSpecs.html) | retrieved_review_required | False |
| [cme_specs](https://www.cmegroup.com/CmeWS/mvc/ContractSpecs/List/productId/446) | retrieved_review_required | True |
| [cme_holidays](https://www.cmegroup.com/tools-information/holiday-calendar.html) | retrieved_review_required | False |
| [cme_settlement](https://www.cmegroup.com/confluence/display/EPICSANDBOX/Platinum) | proxy_or_transport_failure | False |
| [yahoo_quote](https://finance.yahoo.com/quote/PL%3DF/) | retrieved_review_required | False |
| [yahoo_chart](https://query1.finance.yahoo.com/v8/finance/chart/PL%3DF?range=5d&interval=1d) | retrieved_review_required | False |

### Current official contract fields

Retrieved from CME product 446 via the endpoint used by its contract-specification page. These are current contract facts, not historical holiday rules or Yahoo rollover rules.

- ProductName: Platinum Futures
- ContractUnit: 50 troy ounces
- PriceQuotation: U.S. dollars and cents per troy ounce
- SettlementMethod: Deliverable
- TradingHours: {"vandhr": [{"hours": "Sunday 5:00 p.m. - Friday 4:00 p.m. CT with no reporting Monday - Thursday from 4:00 p.m.  -  5:00 p.m. CT", "venue": "CME ClearPort:"}, {"hours": "Sunday - Friday 6:00 p.m. - 5:00 p.m. (5:00 p.m. - 4:00 p.m. CT) with a 60-minute break each day beginning at 5:00 p.m. (4:00 p.m. CT) \n \nTAS: Sunday - Friday 6:00 p.m. - 1:05 p.m. (5:00 p.m. - 12:05 p.m. CT)", "venue": "CME Globex:"}]}
- TerminationOfTrading: {"terminationOfTrading": [{"type": "Default:", "termsOfTrading": "Trading terminates on the third last business day of the contract month."}]}

### Targeted historical provider reconciliation

| Window | Outcome | Shared dates | OHLC identical | Reproduced anomalies | Vendor-only dates |
|---|---|---:|---:|---:|---:|
| first_anomaly | compared | 6 | 6 | 3 | 1 |
| last_anomaly | compared | 7 | 7 | 2 | 0 |
| largest_gap | compared | 5 | 5 | 3 | 55 |

Matching rows show that those anomalies also exist in the current vendor response, not only this workbook. Vendor-only dates establish additional current coverage; they do not prove the cause of the original omission, historical data availability or whether the vendor later revised history. This is a targeted same-provider comparison, not an independent price-source validation. No workbook rows were replaced or filled.

Raw retrieved responses, when available, stay outside Git. HTTP success alone cannot verify session hours, contract rollover, quote-completion semantics or licensing. No browser challenge or proxy policy is bypassed.

## Decision and new test policy

**Production approval remains false.** No new forecast is issued and no model is retrained from these findings.
New final-test observations must become available strictly after `2026-10-20T03:57:40.120238+00:00`. At least 200 eligible unseen observations per horizon are required under the existing minimum gate. The existing inspected workbook is not eligible as a fresh final test.
First verify sources and register the revised calendar/feature policy using development data; seal a separate final period before outcomes or model selection can influence it. Future data do not yet exist in this audit output. Do not mistake an empty prospective policy for a reserved, evaluated holdout.

Current blocker: authoritative vendor/exchange source evidence and sufficient new unseen completed observations. Model development can resume on disclosed development data only after a new preregistered experiment; promotion requires genuinely unseen final evidence.
