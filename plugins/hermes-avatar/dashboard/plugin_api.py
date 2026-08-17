"""Hermes Digital Human dashboard plugin backend.

The browser never receives provider credentials. The plugin talks to the local
Hermes OpenAI-compatible API server when available and falls back to a
tool-disabled in-process Hermes turn when the API server is not running.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterable, Deque, Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from hermes_constants import get_process_hermes_home

router = APIRouter()

_MAX_MESSAGE_CHARS = 8_000
_MAX_TURNS = 10
_MAX_AVATAR_BYTES = 25 * 1024 * 1024
_GLB_MAGIC = b"glTF"
_DIRECT_AGENT_LOCK = threading.Lock()


class CharacterProvider(Protocol):
    """Narrow provider contract consumed by the Digital Human API layer."""

    name: str

    def configured(self) -> bool: ...

    def health(self) -> dict[str, object]: ...

    def get_task(self, task_id: str) -> dict[str, object]: ...

    def submit_prerig_check(self, task_id: str) -> dict[str, object]: ...

    def submit_rig(
        self,
        task_id: str,
        *,
        out_format: str,
        rig_type: str,
        spec: str,
        model_version: str,
    ) -> dict[str, object]: ...


def _load_tripo_provider_module():
    """Load the sibling provider without relying on process working directory."""
    module_name = "hermes_avatar_tripo_provider"
    module = sys.modules.get(module_name)
    if module is None:
        module_path = Path(__file__).with_name("tripo_provider.py")
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load Tripo character provider")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module


_TRIPO_MODULE = _load_tripo_provider_module()
TripoCharacterProvider = _TRIPO_MODULE.TripoCharacterProvider
TripoProviderError = _TRIPO_MODULE.TripoProviderError


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_CHARS)
    conversation_id: str = Field(default="digital-human", min_length=1, max_length=128)


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    transport: str


class TripoRigRequest(BaseModel):
    """Paid rig submission contract; explicit confirmation is mandatory."""

    confirm_cost: bool = False
    out_format: str = Field(default="glb", max_length=8)
    rig_type: str = Field(default="biped", max_length=32)
    spec: str = Field(default="tripo", max_length=16)
    model_version: str = Field(default="v1.0-20240301", max_length=40)


@dataclass
class ConversationMemory:
    turns: Deque[tuple[str, str]] = field(
        default_factory=lambda: deque(maxlen=_MAX_TURNS * 2)
    )

    def build_prompt(self, message: str) -> str:
        if not self.turns:
            return message
        transcript = "\n".join(f"{role}: {text}" for role, text in self.turns)
        return (
            "Continue this conversational exchange naturally. "
            "Do not mention that a transcript was supplied.\n\n"
            f"Recent conversation:\n{transcript}\n\nUser: {message}"
        )

    def append(self, user_message: str, assistant_reply: str) -> None:
        self.turns.append(("User", user_message))
        self.turns.append(("Assistant", assistant_reply))


class AvatarModelStorage:
    """Persist one operator-selected GLB with bounded, atomic writes."""

    def __init__(self, max_bytes: int = _MAX_AVATAR_BYTES) -> None:
        self.max_bytes = max_bytes

    def path(self) -> Path:
        return (
            get_process_hermes_home()
            / "dashboard-assets"
            / "hermes-avatar"
            / "avatar.glb"
        )

    def exists(self) -> bool:
        return self.path().is_file()

    def revision(self) -> str:
        """Return a cheap cache-busting revision for the current persisted model."""
        try:
            stat = self.path().stat()
        except OSError:
            return ""
        return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"

    @staticmethod
    def _validate_glb(path: Path, total_bytes: int) -> None:
        with path.open("rb") as handle:
            header = handle.read(12)
        if len(header) != 12 or header[:4] != _GLB_MAGIC:
            raise ValueError("Avatar file is not a GLB binary")
        version = int.from_bytes(header[4:8], "little")
        declared_length = int.from_bytes(header[8:12], "little")
        if version != 2:
            raise ValueError("Only GLB version 2 is supported")
        if declared_length != total_bytes:
            raise ValueError("GLB header length does not match the uploaded file")

    async def save(
        self,
        chunks: AsyncIterable[bytes],
        content_length: int | None,
    ) -> int:
        if content_length is not None and content_length > self.max_bytes:
            raise OverflowError("Avatar exceeds the upload size limit")
        if content_length is not None and content_length <= 0:
            raise ValueError("Avatar upload is empty")

        target = self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".avatar-",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(fd)
        tmp_path = Path(tmp_name)
        total = 0

        try:
            with tmp_path.open("wb") as handle:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise OverflowError("Avatar exceeds the upload size limit")
                    handle.write(chunk)

            if total == 0:
                raise ValueError("Avatar upload is empty")
            self._validate_glb(tmp_path, total)
            os.replace(tmp_path, target)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            return total
        finally:
            tmp_path.unlink(missing_ok=True)

    def delete(self) -> bool:
        path = self.path()
        if not path.is_file():
            return False
        path.unlink()
        return True

    def response(self) -> FileResponse:
        return FileResponse(
            self.path(),
            media_type="model/gltf-binary",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )


_CONVERSATIONS: dict[str, ConversationMemory] = {}
_AVATAR_STORAGE = AvatarModelStorage()
_TRIPO_PROVIDER: CharacterProvider = TripoCharacterProvider()


def _api_server_url() -> str:
    host = (os.getenv("API_SERVER_HOST") or "127.0.0.1").strip()
    port = (os.getenv("API_SERVER_PORT") or "8642").strip()
    return f"http://{host}:{port}/v1/responses"


def _avatar_model_url() -> str:
    """Return a browser-safe configured GLB URL without proxying arbitrary URLs."""
    value = (os.getenv("HERMES_AVATAR_GLB_URL") or "").strip()
    if not value:
        return ""

    # A single leading slash is same-origin. Protocol-relative URLs (`//host`)
    # and backslashes are rejected because browsers can normalize them into a
    # cross-origin URL even though the raw string appears path-like.
    if value.startswith("/"):
        if value.startswith("//") or "\\" in value:
            return ""
        return value

    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    return ""


def _avatar_descriptor() -> dict:
    if _AVATAR_STORAGE.exists():
        revision = _AVATAR_STORAGE.revision()
        return {
            "avatar_model_configured": True,
            "avatar_model_url": (
                f"/api/plugins/hermes-avatar/avatar-model?v={revision}"
            ),
            "avatar_model_revision": revision,
            "avatar_model_requires_auth": True,
            "avatar_provider": "uploaded-glb",
            "avatar_uploaded": True,
        }

    configured_url = _avatar_model_url()
    return {
        "avatar_model_configured": bool(configured_url),
        "avatar_model_url": configured_url,
        "avatar_model_revision": "",
        "avatar_model_requires_auth": False,
        "avatar_provider": "configured-glb" if configured_url else "procedural",
        "avatar_uploaded": False,
    }


def _health_payload() -> dict:
    return {
        "plugin": "hermes-avatar",
        "version": "0.4.0",
        "api_server_configured": bool((os.getenv("API_SERVER_KEY") or "").strip()),
        "speech": "browser",
        "renderer": "three-glb-with-procedural-fallback",
        "visual_modes": ["human", "hologram"],
        **_avatar_descriptor(),
        "avatar_upload_supported": True,
        "avatar_upload_max_bytes": _MAX_AVATAR_BYTES,
        "character_providers": {
            "tripo": {
                "configured": _TRIPO_PROVIDER.configured(),
                "health_endpoint": "/api/plugins/hermes-avatar/providers/tripo/health",
                "task_endpoint": "/api/plugins/hermes-avatar/providers/tripo/tasks/{task_id}",
                "prerig_endpoint": "/api/plugins/hermes-avatar/providers/tripo/tasks/{task_id}/prerig-check",
                "rig_endpoint": "/api/plugins/hermes-avatar/providers/tripo/tasks/{task_id}/rig",
                "rigging_requires_cost_confirmation": True,
                "credentials": "server-side-only",
            }
        },
        "facial_channels": [
            "blink",
            "jaw",
            "mouth_open",
            "mouth_round",
            "mouth_wide",
            "smile",
            "brow",
            "gaze",
        ],
        "morph_targets": True,
    }


def _request_content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    if value < 0:
        raise HTTPException(status_code=400, detail="Invalid Content-Length")
    return value


def _tripo_http_exception(exc: Exception) -> HTTPException:
    """Translate provider failures without leaking provider credentials."""
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, TripoProviderError):
        provider_status = getattr(exc, "status_code", None)
        if provider_status == 404:
            status_code = 404
        elif provider_status == 429:
            status_code = 429
        elif provider_status is None:
            status_code = 503
        else:
            status_code = 502
        trace_id = getattr(exc, "trace_id", "")
        suffix = f" [trace {trace_id}]" if trace_id else ""
        return HTTPException(status_code=status_code, detail=f"{exc}{suffix}")
    return HTTPException(
        status_code=503,
        detail=f"Tripo operation failed safely ({type(exc).__name__})",
    )


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
    return _health_payload()


@router.get("/providers/tripo/health")
async def tripo_provider_health():
    """Check the configured Tripo credential without creating a generation task."""
    try:
        return await asyncio.to_thread(_TRIPO_PROVIDER.health)
    except Exception as exc:
        raise _tripo_http_exception(exc) from exc


@router.get("/providers/tripo/tasks/{task_id}")
async def tripo_task_status(task_id: str):
    """Inspect one Tripo task without exposing signed output URLs."""
    try:
        return await asyncio.to_thread(_TRIPO_PROVIDER.get_task, task_id)
    except Exception as exc:
        raise _tripo_http_exception(exc) from exc


@router.post("/providers/tripo/tasks/{task_id}/prerig-check")
async def tripo_prerig_check(task_id: str):
    """Submit the free Tripo pre-rig suitability check for a model task."""
    try:
        return await asyncio.to_thread(_TRIPO_PROVIDER.submit_prerig_check, task_id)
    except Exception as exc:
        raise _tripo_http_exception(exc) from exc


@router.post("/providers/tripo/tasks/{task_id}/rig")
async def tripo_rig(task_id: str, body: TripoRigRequest):
    """Submit paid rigging only after the caller explicitly confirms provider cost."""
    if not body.confirm_cost:
        raise HTTPException(
            status_code=409,
            detail=(
                "Tripo rigging is a paid provider operation. "
                "Set confirm_cost=true to submit it."
            ),
        )
    try:
        return await asyncio.to_thread(
            _TRIPO_PROVIDER.submit_rig,
            task_id,
            out_format=body.out_format,
            rig_type=body.rig_type,
            spec=body.spec,
            model_version=body.model_version,
        )
    except Exception as exc:
        raise _tripo_http_exception(exc) from exc


@router.put("/avatar-model")
async def upload_avatar_model(request: Request):
    try:
        uploaded_bytes = await _AVATAR_STORAGE.save(
            request.stream(),
            _request_content_length(request),
        )
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {**_health_payload(), "uploaded_bytes": uploaded_bytes}


@router.get("/avatar-model")
async def get_avatar_model():
    if not _AVATAR_STORAGE.exists():
        raise HTTPException(status_code=404, detail="No uploaded avatar model")
    return _AVATAR_STORAGE.response()


@router.delete("/avatar-model")
async def delete_avatar_model():
    removed = _AVATAR_STORAGE.delete()
    return {**_health_payload(), "removed": removed}


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    message = body.message.strip()
    conversation_id = body.conversation_id.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        reply = await asyncio.to_thread(_call_api_server, message, conversation_id)
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
        reply = await asyncio.to_thread(_direct_hermes_turn, message, conversation_id)
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
