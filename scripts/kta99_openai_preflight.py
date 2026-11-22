#!/usr/bin/env python3
"""Read-only readiness check for switching @KTA99bot to direct OpenAI API.

This script never writes to Hermes config, prints API keys, or calls the
Telegram API. The optional API probe sends the key only to api.openai.com.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import yaml

DEFAULT_MODEL = "gpt-5.6-sol"
OPENAI_HOST = "api.openai.com"


def inspect(config_path: Path, environment: dict[str, str], *, probe: bool = False) -> dict:
    """Return nonsensitive status; fail closed on missing/unsafe settings."""
    status: dict = {
        "config_readable": False,
        "openai_key_configured": bool(environment.get("OPENAI_API_KEY", "").strip()),
        "openai_endpoint_safe": True,
        "current_provider": None,
        "current_model": None,
        "probe_result": "not_requested",
        "ready_for_cutover": False,
    }

    custom_endpoint = environment.get("OPENAI_BASE_URL", "").strip()
    if custom_endpoint:
        parsed = urlsplit(custom_endpoint)
        status["openai_endpoint_safe"] = (
            parsed.scheme == "https"
            and parsed.hostname == OPENAI_HOST
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        )

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return status
        model = data.get("model", {})
        if not isinstance(model, dict):
            return status
        status["config_readable"] = True
        status["current_provider"] = str(model.get("provider") or "auto")
        status["current_model"] = str(model.get("default") or model.get("model") or "")
    except (OSError, UnicodeError, yaml.YAMLError):
        return status

    if not (
        status["config_readable"]
        and status["openai_key_configured"]
        and status["openai_endpoint_safe"]
    ):
        return status

    if probe:
        # Explicitly contact only OpenAI's official API host; do not follow
        # redirects which could forward Authorization to another endpoint.
        class NoRedirects(__import__("urllib.request", fromlist=["HTTPRedirectHandler"]).HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None

        req = Request(
            f"https://{OPENAI_HOST}/v1/models/{DEFAULT_MODEL}",
            headers={"Authorization": "Bearer " + environment["OPENAI_API_KEY"].strip()},
        )
        try:
            opener = __import__("urllib.request", fromlist=["build_opener"]).build_opener(NoRedirects)
            with opener.open(req, timeout=12) as response:
                status["probe_result"] = "ok" if response.status == 200 else "unexpected_status"
        except HTTPError as exc:
            status["probe_result"] = f"http_{exc.code}"
        except (OSError, URLError):
            status["probe_result"] = "network_error"

        if status["probe_result"] != "ok":
            return status

    status["ready_for_cutover"] = True
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "config.yaml",
        help="Explicit Hermes config path for the bot instance",
    )
    parser.add_argument(
        "--probe-api",
        action="store_true",
        help="Make one read-only GET /v1/models/gpt-5.6-sol request to OpenAI",
    )
    args = parser.parse_args()
    result = inspect(args.config, dict(os.environ), probe=args.probe_api)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ready_for_cutover"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
