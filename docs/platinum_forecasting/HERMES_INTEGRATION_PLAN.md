# Hermes integration decision

**No production integration or forecast skill was activated.** Every evaluated
horizon failed acceptance and source-provenance gates remain unresolved.
The existing Hermes CLI, tools, skills loader, plugin registration, toolsets and
Telegram routing were inspected. CLI + optional skill is the appropriate edge
extension; no new core tool, gateway patch, HTTP server or bot is justified.

The implemented transport is `python -m platinum_forecasting.cli status`:
it returns JSON with daily/hourly scores, gate decisions and an Arabic research
status. This can be invoked through Hermes's existing `terminal` tool for
review. It does not return a current forecast. No Telegram message was sent.

## Conditional activation after a future successful experiment

1. Obtain verified historical/current completed-bar data, contract-roll rules,
   calendar and usable terms. Reserve new unseen data; never retune using this
   experiment's holdout. Apply independent gates for each dataset/horizon.
2. Export a compatible artifact and a manifest carrying dataset version,
   feature schema, training config, validation/holdout metrics, artifact
   SHA-256, model ID, approval status and rollback reference. Current serving
   supports safe JSON linear weights only; other model exporters require their
   own tests. Do not set approval based on a successful training exit code.
3. Implement and verify a current-data provider for `DataSnapshot`: completed
   bars, information cutoff, actual future target timestamp and verified
   exchange calendar. Inject it into `ForecastService`. No user chat can
   declare these facts or alter operator-owned registry files.
4. Write an optional finance skill, using native `terminal` for the fixed
   approved CLI path. Handle requests such as «توقع الجلسة القادمة»، «اعرض دقة
   النموذج الساعي»، «ما آخر سعر استُخدم؟». Reject unknown horizons. Never fall
   back to a rejected model or silently mix daily/hourly artifacts.
5. Test actual skill loading through `tools.skills_tool.skill_view`, its CLI
   subprocess result and existing gateway routing using isolated HERMES_HOME.
   These production skill/Telegram tests were **not executed**, because no
   model was accepted. Do not label Python service tests as Telegram tests.
6. Reuse the operator's authenticated existing Telegram connection. Require
   human review before installation/activation, with no new bot, copied
   token, outbound unsolicited messages, auto-trading or account linkage.

## Mobile Arabic response contract

For accepted predictions, display instrument (عقود البلاتين الآجلة PL=F), native
USD/troy-ounce units, last price/time, predicted price/change/direction, empirical
prediction interval and its measured coverage, horizon in actual observed
bars, issuance/cutoff/target times and model ID. Render user-facing times in
Asia/Riyadh; retain UTC in machine JSON. Do not say spot price, guaranteed
accuracy, or an uncalibrated confidence percentage.

Current truthful response: «لا يوجد نموذج بلاتين معتمد للإنتاج. لم تحقق النماذج
تحسنًا موثوقًا مقابل Baseline؛ أفق 24 شمعة غير قابل للتقييم بهذه البيانات.»
