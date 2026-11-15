---
name: luma-publisher
description: Preview and publish Luma posts to X, TikTok and Telegram.
version: 1.0.0
author: MoatasimFaroog1111
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    category: social-media
    tags: [luma, social-media, publishing, telegram, tiktok, x]
---

# Luma Publisher Skill

This skill lets Hermes preview Luma Store campaigns and publish approved posts to X, TikTok and a Telegram channel using existing Python scripts. All default CLI invocations are previews only. It **must not** schedule, auto-post, or circumvent the explicit operator confirmation.

## When to Use

- Draft or preview a Luma launch post before release.
- Publish an explicitly approved X thread, TikTok video, or Telegram channel message.
- Diagnose missing API configuration without exposing credentials.

## Prerequisites

- Python 3.11+ and dependencies from repository `requirements.txt` (or install Tweepy 4.17.0 into the existing Hermes environment; `requests` and `python-dotenv` are already core dependencies).
- Provide credentials through the runtime environment or a local untracked `.env`; **never** paste credentials into prompts, terminal output, or GitHub.
- X: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` (authorized write access).
- TikTok: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`, `TIKTOK_ACCESS_TOKEN`, `TIKTOK_REFRESH_TOKEN` and the correct posting scopes.
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`; the bot must be permitted to post to that channel.
- Video files and marketing assets remain outside the Git repository. Use absolute paths to selected assets.

## How to Run

Use Hermes `terminal` to execute the following from the repository root. Commands are previews unless `--publish` is explicitly passed.

```bash
python luma_publisher/publish_x.py
python luma_publisher/publish_tiktok.py --media /private/path/video.mp4
python luma_publisher/channel_post.py --text "Luma Store launch preview"
```

## Quick Reference

| Destination | Preview | Publish after interactive confirmation |
| --- | --- | --- |
| X | `python luma_publisher/publish_x.py` | `python luma_publisher/publish_x.py --publish` |
| TikTok inbox | `python luma_publisher/publish_tiktok.py --media /private/path/video.mp4` | `python luma_publisher/publish_tiktok.py --media /private/path/video.mp4 --publish` |
| Telegram | `python luma_publisher/channel_post.py --text "Message"` | `python luma_publisher/channel_post.py --text "Message" --publish` |

TikTok direct posting requires explicit `--mode direct --publish` and API permission. `--dry-run` always overrides `--publish` for the original X and TikTok scripts. `--auth` in the TikTok script is an interactive account-linking operation, never an automatic publishing step.

## Procedure

1. Determine the intended account, copy and media. Confirm the operator owns/controls that account and approves the content.
2. Preview locally with no credentials and no network calls. Inspect the prepared text and media path.
3. Request explicit approval for each destination and each content payload before any `--publish` invocation.
4. If approved, invoke the specific command in a trusted interactive terminal, handle the confirmation prompt, and inspect platform response.
5. Record success identifiers privately. On failure, report a sanitized error; do not expose authorization URLs, tokens, or request headers.

## Pitfalls

- Never commit `.env`, cached Python files, private media, download directories or authentication responses.
- X threads are sequential: partial success is possible. Do not automatically retry a whole thread or duplicate already published posts.
- TikTok inbox is **not** public posting; the account owner must finish in the TikTok app. Direct mode may require account authorization and platform review.
- Existing TikTok script writes refreshed tokens to `.env` in its current working directory; only run credential renewal from a secure, writable workspace.
- Installing a skill or rebuilding Hermes does **not** publish content or populate secrets automatically.

## Verification

Run `python -m pytest tests/skills/test_luma_publisher_skill.py -q` and `python -m compileall -q luma_publisher`. Default previews should make no HTTP requests and should not ask for credentials. Smoke-test live APIs only after the operator separately authorizes that test.
