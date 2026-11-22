# @KTA99bot — safe OpenAI default cutover

**Status:** prepared, NOT applied to production.  No Telegram token, GitHub
write guard, toolset, cron job, account, skills, database, or deployment
configuration is changed by this PR.

## Existing architecture verified

- Bot: @KTA99bot uses the Hermes Telegram gateway.
- Repository: MoatasimFaroog1111/hermos, default branch main.
- Fly app in fly.toml / deploy workflow: hermos-moatasim.
- Hermes supports provider \`openai-api\` via OpenAI Responses API.
- Hermes supports provider \`deepseek\` and \`/model\` with \`--global\`,
  \`--session\`, and \`--provider\` options. No gateway fork is needed.
- The verified current Telegram model reported earlier by the bot was
  \`deepseek-v4-pro\`; confirm the *live* value before changing it.

## Safety prerequisites

1. Confirm the Fly app and bot are healthy, and record live model + provider.
2. On Fly, add \`OPENAI_API_KEY\` as a **runtime secret**; do not place it in
   code, GitHub commits, chat, PR comments, shell history, or a public file.
   Ensure API billing/model access is enabled. If using a nonstandard
   \`OPENAI_BASE_URL\`, stop: this procedure is for direct OpenAI only.
3. Keep the existing \`DEEPSEEK_API_KEY\` / provider configuration intact.
4. Confirm whether this gateway serves channels beyond Telegram. The
   \`--global\` switch changes the gateway default, including other clients
   and scheduled jobs that follow the default. If other channels/jobs must
   keep DeepSeek, configure isolated Telegram profile routing first.
5. Confirm API quotas/usage alert; do not assume ChatGPT subscription
   credits cover API usage.

## Preflight — read-only

This repo includes \`scripts/kta99_openai_preflight.py\`, designed to run
*inside the deployed Hermes runtime* once the script is in that image.

\`\`\`bash
# On the Fly machine/container with the same HERMES_HOME and environment
# as the running gateway. The command prints flags, never credential values.
python /opt/hermes/scripts/kta99_openai_preflight.py --probe-api
\`\`\`

- This checks the config shape, key presence, official API host, and a
  read-only OpenAI model lookup. It does **not** test Telegram delivery or
  the agent's tool access.
- Exit code 0 = prerequisites verified. Exit code 2 = stop; inspect the
  boolean/status fields (no secrets are printed).
- It is not a substitute for checking production health and the exact
  active profile. It intentionally changes no files or external services.

## Cutover from the bot (after all prerequisites)

First record the live model and provider using \`/model\` in Telegram
and preserve the previous config (e.g. copy \`$HERMES_HOME/config.yaml\`
to a secured backup on the persistent volume).

For a **bot-only trial** (does not replace the global default):

\`\`\`text
/model gpt-5.6-sol --provider openai-api --session
\`\`\`

Send one harmless question and one read-only Hermes tool request. Confirm
both replies are delivered to Telegram and that existing tool permissions
and GitHub approval guards remain effective.

If the gateway is dedicated to this bot, and the trial is good, persist:

\`\`\`text
/model gpt-5.6-sol --provider openai-api --global
\`\`\`

The supported initial model is \`gpt-5.6-sol\` (present in this repository's
model catalog). Newer OpenAI models should be validated against the deployed
Hermes version before adopting them; **do not blindly switch to a model ID
not in the deployed provider catalog**.

## Fast rollback

The following restores the previous reported provider/model without
replacing Hermes, changing tools, or touching the Telegram token:

\`\`\`text
/model deepseek-v4-pro --provider deepseek --global
\`\`\`

If your actual recorded prior model was different, restore that exact pair.
If the gateway fails to respond, restore the secured pre-cutover
\`config.yaml\` from inside the Fly machine and restart only the gateway
under its normal supervisor. Do not redeploy a different code revision
as the first rollback action.

## Acceptance checklist

- [ ] Fly app healthy before and after.
- [ ] Telegram bot replies normally; no duplicate polling/gateway instances.
- [ ] The first OpenAI answer identifies the configured provider/model.
- [ ] A read-only tool call succeeds under the existing authorization rules.
- [ ] Existing GitHub MCP write approval still gates writes; delete guard
      remains blocked.
- [ ] DeepSeek manual switch still works, and returning to OpenAI works.
- [ ] Secrets remain in Fly/runtime stores; none in GitHub or chat.
- [ ] Existing jobs, memories, sessions, skills and Luma publisher
      configurations remain unchanged.
- [ ] API usage limits and fallback procedure are documented for operators.
