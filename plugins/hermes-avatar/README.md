# Hermes Digital Human

A bundled Hermes Dashboard plugin that adds a responsive, voice-enabled 3D
digital-human interface without coupling avatar concerns to the dashboard core.

## What ships

Version **0.2.0** adds a more human presentation while retaining the original
hologram mode:

- Procedural WebGL human bust rendered locally in the browser.
- Human and Hologram visual modes with instant switching.
- Separate facial channels for blink, jaw, mouth open, mouth round, mouth wide,
  smile, brow lift, gaze and head pose.
- Eyes with iris/pupil tracking for lightweight eye contact.
- Idle, listening, thinking, speaking, and error visual states.
- Browser speech recognition when supported.
- Browser Text-to-Speech with Arabic/English voice selection.
- Viseme-like articulation for Arabic and English with fallback speech cadence.
- Text chat fallback on every browser.
- Server-side bridge to the existing Hermes OpenAI-compatible API server.
- Safe direct fallback when the API server is unavailable.
- Responsive desktop/tablet/mobile layout and reduced-motion support.
- No provider API key is exposed to browser JavaScript.
- No CDN, remote 3D asset, or new frontend dependency is required.

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
                    +-- VisemeMapper ---> open / round / wide / jaw
        |
        +-- AvatarController -----------> facial / state channels
                    |
                    +-- DigitalHumanRenderer -> WebGL
```

### SOLID mapping

- **Single Responsibility**: transport, viseme mapping, speech input, speech
  output, avatar state, rendering, and React composition are separate units.
- **Open/Closed**: `DigitalHumanRenderer` can be replaced by a GLTF/Ready Player
  Me renderer; speech can be replaced by ElevenLabs or Google TTS without
  changing chat composition.
- **Liskov Substitution**: voice/render adapters expose small behavior surfaces
  (`speak`, `listen`, `setMode`, `destroy`) and can be substituted.
- **Interface Segregation**: the browser only receives the methods needed by
  each concern; the AI transport is not mixed with rendering or speech.
- **Dependency Inversion**: the page composes adapters and talks to Hermes
  through the dashboard plugin API instead of importing provider SDKs.

## Rendering strategy

The default renderer is intentionally self-contained. It builds the human from
small WebGL meshes and keeps all animation channels renderer-independent. This
means Hermes can run on Railway, localhost, desktop, or mobile browsers without
needing a remote 3D CDN.

`Human` mode uses natural skin, eye, hair, lip and clothing materials with
diffuse/specular/rim lighting. `Hologram` mode maps the same animation rig to
translucent cyan/mint materials and scan-line lighting.

The procedural human is the lightweight default, not the final limit of the
architecture. A production GLB can replace only the renderer adapter.

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

`VisemeMapper` converts speech boundary characters into four independent mouth
channels: `open`, `round`, `wide`, and `jaw`. When the browser does not emit
useful boundary timing, `BrowserSpeechOutput` drives a natural fallback cadence.

A future TTS adapter can supply real phoneme timing while leaving
`DigitalHumanPage`, `AvatarController`, and Hermes transport unchanged.

## GLB / Ready Player Me upgrade path

A photorealistic Ready Player Me or custom GLB character can be added as a new
renderer adapter without changing the current chat/voice architecture:

1. Load the GLB locally or from an operator-approved asset origin.
2. Map controller channels to model morph targets such as `eyeBlinkLeft`,
   `eyeBlinkRight`, `jawOpen`, `mouthSmile`, and viseme targets.
3. Replace the procedural material stage with PBR skin/hair/eye materials.
4. Optionally replace browser TTS with a provider that emits phoneme/alignment
   timing.
5. Keep `HermesAvatarClient`, session handling, and server-side credentials
   unchanged.

## Runtime files

The active v0.2 experience is:

```text
dashboard/
├── manifest.json
├── plugin_api.py
└── dist/
    ├── realistic.js
    └── realistic.css
```

The older `index.js` / `style.css` pair remains on the feature branch only as a
rollback reference while v0.2 is reviewed.

## Validation

From the repository root:

```bash
node --check plugins/hermes-avatar/dashboard/dist/realistic.js
python -m py_compile plugins/hermes-avatar/dashboard/plugin_api.py
python -m json.tool plugins/hermes-avatar/dashboard/manifest.json >/dev/null
```
