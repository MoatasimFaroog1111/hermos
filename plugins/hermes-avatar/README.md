# Hermes Digital Human

A bundled Hermes Dashboard plugin that adds a responsive, voice-enabled 3D
avatar interface without coupling avatar concerns to the dashboard core.

## What ships

- WebGL holographic bust rendered directly in the browser.
- Idle, listening, thinking, speaking, and error visual states.
- Procedural blinking, subtle breathing/head tracking, and mouth animation.
- Browser speech recognition when supported.
- Browser Text-to-Speech with Arabic/English voice selection.
- Text chat fallback on every browser.
- Server-side bridge to the existing Hermes OpenAI-compatible API server.
- Safe direct fallback when the API server is unavailable.
- Responsive desktop/tablet/mobile layout.
- No provider API key is exposed to browser JavaScript.

The dashboard plugin auto-registers as the **Digital Human** tab because it is
bundled under `plugins/hermes-avatar/dashboard/`.

## Architecture

The plugin follows a ports-and-adapters style so visual/voice providers can be
replaced independently.

```text
DigitalHumanPage (React composition root)
        |
        +-- HermesAvatarClient ---------> /api/plugins/hermes-avatar/chat
        |
        +-- BrowserSpeechInput ---------> Web Speech Recognition
        |
        +-- BrowserSpeechOutput --------> Web Speech Synthesis
        |
        +-- AvatarController -----------> facial / state channels
                    |
                    +-- HologramRenderer -> WebGL
```

### SOLID mapping

- **Single Responsibility**: transport, speech input, speech output, avatar
  state, rendering, and React composition are separate classes/components.
- **Open/Closed**: `HologramRenderer` can be replaced by a GLTF/Ready Player Me
  renderer; speech can be replaced by ElevenLabs or Google TTS without
  changing chat composition.
- **Liskov Substitution**: voice/render adapters expose small behavior surfaces
  (`speak`, `listen`, `subscribe`, `destroy`) and can be substituted.
- **Interface Segregation**: the browser only receives the methods needed by
  each concern; the AI transport is not mixed with rendering or speech.
- **Dependency Inversion**: the page composes adapters and talks to Hermes
  through the dashboard plugin API instead of importing provider SDKs.

## Hermes connection

The backend tries the existing local Hermes API server first:

```text
POST http://127.0.0.1:8642/v1/responses
```

If `API_SERVER_KEY` is configured, the request uses a named conversation so
Hermes can retain server-side conversation continuity.

If the API server is not available, the plugin falls back to an in-process
Hermes turn with an intentionally unknown toolset, so no tool execution is
advertised from the fallback channel.

For full agent tools and richer progress/approval UX, run the normal Hermes API
server alongside the dashboard:

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=<a-strong-secret>
hermes gateway
```

Provider credentials remain on the server.

## Voice and lip sync

The default speech adapters intentionally use browser capabilities to keep the
plugin lightweight and avoid another billable service.

`BrowserSpeechOutput` drives the mouth channel from speech boundary events plus
a small viseme-like heuristic. Browsers that do not emit useful boundary events
receive a natural fallback mouth cadence while speech is active.

The next production upgrade can implement a real audio analyser / viseme stream
inside a replacement speech adapter without touching the avatar page.

## Future avatar provider

A photorealistic Ready Player Me or custom GLB character can be added as a new
renderer adapter. The recommended upgrade path is:

1. Load a GLB with morph targets.
2. Map the controller channels to `eyeBlinkLeft`, `eyeBlinkRight`,
   `jawOpen`, `mouthSmile`, etc.
3. Drive visemes from a TTS provider that emits alignment/phoneme timing.
4. Keep `HermesAvatarClient` unchanged.

## Validation

From the repository root:

```bash
node --check plugins/hermes-avatar/dashboard/dist/index.js
python -m py_compile plugins/hermes-avatar/dashboard/plugin_api.py
python -m json.tool plugins/hermes-avatar/dashboard/manifest.json >/dev/null
```
