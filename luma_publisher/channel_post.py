"""Publish an approved post to a Telegram channel; default is preview only."""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def publish_channel(text: str, media: Path | None = None, *, publish: bool = False) -> bool:
    """Return True only when Telegram confirms the send."""
    if not text.strip():
        raise ValueError("A non-empty --text is required")
    if media is not None and (not media.is_file() or media.suffix.lower() not in {".jpg", ".jpeg", ".png", ".mp4"}):
        raise ValueError("--media must be an existing JPG, PNG, or MP4 file")
    if media and media.suffix.lower() == ".mp4":
        method, field = "sendVideo", "video"
    elif media:
        method, field = "sendPhoto", "photo"
    else:
        method, field = "sendMessage", "text"
    print(f"Telegram channel preview: method={method}; text={text!r}; media={media.name if media else None}")
    if not publish:
        print("DRY_RUN: no message was sent.")
        return False
    if input("Send this post to the Telegram channel? Type YES: ").strip() != "YES":
        print("Cancelled.")
        return False
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not channel_id:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID are required")
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = {"chat_id": channel_id, "caption": text} if media else {"chat_id": channel_id, "text": text}
    try:
        if media:
            with media.open("rb") as handle:
                response = requests.post(url, data=data, files={field: handle}, timeout=60)
        else:
            response = requests.post(url, data=data, timeout=30)
        result = response.json()
        if response.status_code != 200 or not result.get("ok"):
            raise RuntimeError("Telegram declined the request")
    except requests.RequestException:
        # Never include the token-bearing URL in exception output.
        raise RuntimeError("Telegram network request failed; inspect private server logs") from None
    except (ValueError, KeyError):
        raise RuntimeError("Telegram returned an unexpected response") from None
    print("Telegram confirmed delivery.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or publish to a Telegram channel")
    parser.add_argument("--text", required=True)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--publish", action="store_true", help="Post only with confirmation")
    args = parser.parse_args()
    try:
        publish_channel(args.text, args.media, publish=args.publish)
    except (ValueError, EnvironmentError, RuntimeError) as exc:
        print(f"Telegram publisher: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
