# Data foundation decision after source audit

## Confirmed observations

The original workbook remains unchanged. Its SHA-256 is recorded in summary.json.
All 473 daily OHLC violations occur during 1999–2011; none occurs from the start
of the workbook's hourly coverage onward. Of those rows, 459 have close outside
low/high, 61 have open outside, and four have high below low; categories overlap.
The disjoint reason counts appear in the audit evidence.

Three bounded historical Yahoo requests compared 18 shared dates, all with
matching OHLC values, reproducing eight anomalous rows. The largest-gap request
also returned 55 dates not present in the workbook. This confirms current vendor
coverage omissions from the workbook in that window, but not why they occurred:
original export logic and historical vendor revisions remain possible causes.
Reproduction by the same vendor is not independent price validation.

All four USD/kg conversion columns in both datasets match the workbook's stated
32.15074657 factor. Currency/instrument identity is additionally supported by
Yahoo metadata (PL=F, FUTURE, USD) and current CME contract specifications
(product 446, PL, 50 troy ounces, USD per troy ounce, deliverable). The retrieved
Yahoo quote page displays Platinum Jan 27. A generic PL=F history must not be
called a verified front-month or back-adjusted series without a documented
mapping policy.

CME's current Globex specification supports 17:00–16:00 Chicago trading with a
daily 16:00–17:00 break. DST-aware diagnostics find 392 maintenance-consistent
and 88 weekend-consistent gaps. The remaining gap classifications, including
half-hour anchoring and unusual closures, need actual historical holiday and
vendor session rules. Current hours do not certify every historical closure.

## Correction to the earlier conservative research interpretation

The earlier study broke every hourly segment at any non-one-hour interval and
excluded non-hour-aligned timestamps. That was an explicit conservative policy,
not evidence that all such intervals are missing observations or that all
half-hour-aligned records are invalid. The reported 11 examples for a 24-bar
horizon apply to that policy. They do not prove that the underlying two-year
dataset has only 11 usable examples under a correctly verified session calendar.

The old final scores and failed promotion decisions remain valid statements
about that frozen experiment. They cannot be reused to select a new calendar,
feature policy or model. No old selection manifest, source digest, consumed
marker or holdout prediction was changed in this follow-up.

## Controlled rebuild steps

1. Preserve the original workbook and all old raw/cleaned outputs. New source
   captures get acquisition time, exact request, byte digest, instrument
   metadata, explicit vendor vintage and separate daily/hourly dataset IDs.
2. Resolve historical calendar/short-session semantics and quote completion.
   The holiday catalogue was retrieved, but no complete 1997–2026 holiday
   calendar was constructed or approved. The official settlement-procedure
   link redirects to cmegroupclientsite.atlassian.net; the proxy denied access
   during this audit. That hostname was added to the saved network draft.
3. Verify Yahoo's daily close versus settlement definition and historical
   contract mapping/adjustment rules. CME expiry rules alone do not establish
   Yahoo's rollover date, active-contract choice or treatment of price gaps.
   No unsupported adjustment or automatic settlement-price repair is allowed.
4. Reacquire explicitly missing dates from a licensed, identified source into
   a new staging dataset. The three small window responses are locally cached
   evidence, not a complete repaired history. Never forward/backward fill or
   resample daily data into supposed observed hourly bars.
5. Keep conflicting OHLC in quarantine pending source reconciliation. A
   close-only modeling experiment could be proposed only after close/settlement
   semantics are verified, with OHLC features excluded by declared design.
   Do not silently swap high/low or clamp the close into the range.
6. Implement verified session-aware adjacency for actual observed bars. Retain
   timezone-aware UTC timestamps and original vendor/session labels; account
   for Chicago DST, actual holidays and Yahoo's New York metadata. An inferred
   regular-hours template does not authorize production adjacency.
7. Freeze a new bounded development experiment on disclosed development data.
   Sealed final observations must be genuinely new, completed and available
   after PROSPECTIVE_TEST_POLICY.json's exclusive cutoff, with at least 200
   eligible observations per horizon and the predeclared overlap controls.

## Current state

Read-only audit, targeted reconciliation, tested diagnostic code and prospective
policy are delivered. A complete repaired dataset, verified historical exchange
calendar, retrained model and new independent final evaluation are **not**
delivered or claimed. These require unresolved source evidence and future
unseen observations. No production promotion, Hermes forecast activation,
Telegram change, trading or paid subscription occurred.
