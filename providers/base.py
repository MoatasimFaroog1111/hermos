"""Provider profile base class.

A ProviderProfile declares everything about an inference provider in one place:
auth, endpoints, client quirks, request-time quirks. The transport reads this
instead of receiving 20+ boolean flags.

Provider profiles are DECLARATIVE — they describe the provider's behavior.
They do NOT own client construction, credential rotation, streaming, or model
catalog I/O. Live model discovery is delegated to ``ModelCatalogClient``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from providers.model_catalog import ModelCatalogClient

# Sentinel for "omit temperature entirely" (Kimi: server manages it)
OMIT_TEMPERATURE = object()


@dataclass
class ProviderProfile:
    """Base provider profile — subclass or instantiate with overrides."""

    # ── Identity ─────────────────────────────────────────────
    name: str
    api_mode: str = "chat_completions"
    aliases: tuple = ()

    # ── Human-readable metadata ───────────────────────────────
    display_name: str = ""       # e.g. "GMI Cloud" — shown in picker/labels
    description: str = ""        # e.g. "GMI Cloud (multi-model direct API)" — picker subtitle
    signup_url: str = ""         # e.g. "https://www.gmicloud.ai/" — shown during setup

    # ── Auth & endpoints ─────────────────────────────────────
    env_vars: tuple = ()
    base_url: str = ""
    models_url: str = ""  # explicit models endpoint; falls back to {base_url}/models
    auth_type: str = "api_key"   # api_key|oauth_device_code|oauth_external|copilot|aws_sdk
    supports_health_check: bool = True  # False → doctor skips /models probe for this provider

    # ── Vision support ────────────────────────────────────────
    # True when the provider's API accepts image content inside
    # tool-result messages natively.  Set on providers that expose
    # multimodal models via tool results (Anthropic Messages API,
    # OpenAI Chat Completions, Gemini, MiniMax, etc.).
    # Falls back to model-catalog lookup when False and the provider
    # has no registered profile.
    supports_vision: bool = False

    # True when the provider's API accepts list-type tool message
    # content (multipart with image_url parts).  Defaults to True for
    # backward compatibility.  Set to False for providers that accept
    # multimodal user messages but reject list-type tool content
    # (e.g. Xiaomi MiMo, which returns 400 "text is not set").
    supports_vision_tool_messages: bool = True

    # ── Model catalog ─────────────────────────────────────────
    # fallback_models: curated list shown in /model picker when live fetch fails.
    # Only agentic models that support tool calling should appear here.
    fallback_models: tuple = ()

    # hostname: base hostname for URL→provider reverse-mapping in model_metadata.py
    # e.g. "api.gmi-serving.com". Derived from base_url when empty.
    hostname: str = ""

    # ── Client-level quirks (set once at client construction) ─
    default_headers: dict[str, str] = field(default_factory=dict)

    # ── Request-level quirks ─────────────────────────────────
    # Temperature: None = use caller's default, OMIT_TEMPERATURE = don't send
    fixed_temperature: Any = None
    default_max_tokens: int | None = None
    default_aux_model: str = (
        ""  # cheap model for auxiliary tasks (compression, vision, etc.)
    )
    # empty = use main model

    # ── Infrastructure ports ─────────────────────────────────
    # Optional injection point used by tests, embedders, and alternate
    # composition roots. Excluded from repr/equality so the profile remains a
    # declarative value object for normal callers.
    catalog_client: ModelCatalogClient | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    # ── Hooks (override in subclass for complex providers) ───

    def get_hostname(self) -> str:
        """Return the provider's base hostname for URL-based detection.

        Uses self.hostname if set explicitly, otherwise derives it from base_url.
        e.g. 'https://api.gmi-serving.com/v1' → 'api.gmi-serving.com'
        """
        if self.hostname:
            return self.hostname
        if self.base_url:
            from urllib.parse import urlparse

            return urlparse(self.base_url).hostname or ""
        return ""

    def prepare_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Provider-specific message preprocessing.

        Called AFTER codex field sanitization, BEFORE developer role swap.
        Default: pass-through.
        """
        return messages

    def build_extra_body(
        self, *, session_id: str | None = None, **context: Any
    ) -> dict[str, Any]:
        """Provider-specific extra_body fields.

        Merged into the API kwargs extra_body. Default: empty dict.
        """
        return {}

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Provider-specific kwargs split between extra_body and top-level api_kwargs.

        Returns (extra_body_additions, top_level_kwargs).
        The transport merges extra_body_additions into extra_body, and
        top_level_kwargs directly into api_kwargs.

        This split exists because some providers put reasoning config in
        extra_body (OpenRouter: extra_body.reasoning) while others put it
        as top-level api_kwargs (Kimi: api_kwargs.reasoning_effort).

        Default: ({}, {}).
        """
        return {}, {}

    def default_vision_model(self) -> str | None:
        """Return a default vision model id for this provider, or None.

        Overrideable hook for providers that discover their vision default at
        runtime (e.g. from a live catalog) rather than pinning one in code.
        Keeps provider-specific vision discovery inside the provider's plugin
        instead of a name-check branch in shared vision resolution.

        Default: None (no provider-specific vision model — the caller falls
        back to the user's chat model or the aggregator chain).
        """
        return None

    def get_max_tokens(self, model: str | None) -> int | None:
        """Return the default max_tokens cap for *model*.

        Overrideable hook for providers that need per-model output caps —
        e.g. a relay that fronts several upstream backends, each with a
        different completion-token limit. The transport calls this when
        the user hasn't set an explicit max_tokens.

        Default: return self.default_max_tokens (the static profile field),
        ignoring the model name. Override in a subclass to vary the cap
        per-model.
        """
        return self.default_max_tokens

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Fetch the live model list through the configured catalog port.

        Compatibility is unchanged for callers and subclasses: ``models_url``
        still wins, followed by the caller-provided ``base_url``, then the
        profile's own ``base_url``. The default adapter sends Bearer auth and
        ``default_headers`` and preserves credential-safe redirect handling.

        A custom ``catalog_client`` may be injected at construction time for
        alternate transports or deterministic tests. Callers must still fall
        back to their static model lists when this method returns ``None``.
        """
        from providers.model_catalog import (
            DEFAULT_MODEL_CATALOG_CLIENT,
            ModelCatalogRequest,
        )

        client = self.catalog_client or DEFAULT_MODEL_CATALOG_CLIENT
        return client.fetch_models(
            ModelCatalogRequest(
                provider_name=self.name,
                base_url=base_url or self.base_url,
                models_url=self.models_url,
                api_key=api_key,
                default_headers=self.default_headers,
                timeout=timeout,
            )
        )
