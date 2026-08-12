"""Hermes Digital Human dashboard plugin backend.

The browser never receives provider credentials. The plugin talks to the local
Hermes OpenAI-compatible API server when available and falls back to a
tool-disabled in-process Hermes turn when the API server is not running.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

_MAX_MESSAGE_CHARS = 8_000
_MAX_TURNS = 10
_DIRECT_AGENT_LOCK = threading.Lock()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_CHARS)
    conversation_id: str = Field(default="digital-human", min_length=1, max_length=128)


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    transport: str


@dataclass
class ConversationMemory:
    turns: Deque[tuple[str, str]] = field(
        default_factory=lambda: deque(maxlen=_MAX_TURNS * 2)
    )

    def build_prompt(self, message: str) -> str:
        if not self.turns:
            return message
        transcript = "\n".join(
            f"{role}: {text}" for role, text in self.turns
        )
        return (
            "Continue this conversational exchange naturally. "
            "Do not mention that a transcript was supplied.\n\n"
            f"Recent conversation:\n{transcript}\n\nUser: {message}"
        )

    def append(self, user_message: str, assistant_reply: str) -> None:
        self.turns.append(("User", user_message))
        self.turns.append(("Assistant", assistant_reply))


_CONVERSATIONS: dict[str, ConversationMemory] = {}


def _api_server_url() -> str:
    host = (os.getenv("API_SERVER_HOST") or "127.0.0.1").strip()
    port = (os.getenv("API_SERVER_PORT") or "8642").strip()
    return f"http://{host}:{port}/v1/responses"


def _extract_responses_text(payload: dict) -> str:
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"output_text", "text"}:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _call_api_server(message: str, conversation_id: str) -> str:
    api_key = (os.getenv("API_SERVER_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("API_SERVER_KEY is not configured")

    body = json.dumps(
        {
            "model": "hermes-agent",
            "input": message,
            "conversation": f"digital-human:{conversation_id}",
            "store": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _api_server_url(),
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    reply = _extract_responses_text(payload)
    if not reply:
        raise RuntimeError("Hermes API returned no assistant text")
    return reply


def _direct_hermes_turn(message: str, conversation_id: str) -> str:
    """Safe fallback: run Hermes without toolsets and preserve short UI context."""
    from hermes_cli.oneshot import _run_agent

    with _DIRECT_AGENT_LOCK:
        memory = _CONVERSATIONS.setdefault(conversation_id, ConversationMemory())
        prompt = memory.build_prompt(message)
        reply, _result = _run_agent(
            prompt,
            toolsets=["__digital_human_no_tools__"],
            use_config_toolsets=False,
        )
        reply = (reply or "").strip()
        if not reply:
            raise RuntimeError("Hermes produced no final response")
        memory.append(message, reply)
        return reply


@router.get("/health")
async def health():
    return {
        "plugin": "hermes-avatar",
        "version": "0.2.0",
        "api_server_configured": bool((os.getenv("API_SERVER_KEY") or "").strip()),
        "speech": "browser",
        "renderer": "procedural-webgl-human",
        "visual_modes": ["human", "hologram"],
        "facial_channels": ["blink", "jaw", "mouth_open", "mouth_round", "mouth_wide", "smile", "brow", "gaze"],
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    message = body.message.strip()
    conversation_id = body.conversation_id.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        reply = await asyncio.to_thread(
            _call_api_server, message, conversation_id
        )
        return ChatResponse(
            reply=reply,
            conversation_id=conversation_id,
            transport="api-server",
        )
    except (urllib.error.URLError, TimeoutError, RuntimeError, OSError, ValueError):
        # The dashboard can run without `hermes gateway`; keep the avatar useful
        # by falling back to the configured Hermes model. No toolsets are enabled
        # on this fallback path because there is no approval UI here.
        pass

    try:
        reply = await asyncio.to_thread(
            _direct_hermes_turn, message, conversation_id
        )
        return ChatResponse(
            reply=reply,
            conversation_id=conversation_id,
            transport="direct",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Hermes is not ready for Digital Human chat. "
                "Configure a model provider, or enable the API server. "
                f"Details: {type(exc).__name__}: {exc}"
            ),
        ) from exc
