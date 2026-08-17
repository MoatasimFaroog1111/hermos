# Hermes Digital Human

A bundled Hermes Dashboard plugin that adds a responsive, voice-enabled 3D
Digital Human while keeping AI transport, speech, facial state, model storage,
and rendering as separate responsibilities.

## Version 0.4.0

Digital Human v0.4 makes real GLB characters usable directly from the dashboard:

- **LOAD GLB** uploads a character from the Digital Human page.
- Uploaded avatars persist under the process-level `HERMES_HOME`.
- Uploads are streamed with a 25 MB hard limit; no multipart dependency is
  required.
- The backend validates GLB magic, GLB version 2, and the declared binary
  length before atomically replacing the active avatar.
- Stored models are served from the authenticated plugin API with `no-store`
  and `nosniff` response headers.
- The browser retrieves protected models with the Dashboard SDK's
  `authedFetch`, converts them to a Blob URL, then hands that URL to Three.js.
  This works with both gated-cookie and loopback session-token authentication.
- Replacing an uploaded model changes an `mtime + size` revision in the model
  URL, so React immediately recreates the renderer even though the API path is
  otherwise stable.
- **REMOVE GLB** deletes the uploaded avatar and immediately falls back to a
  configured model URL or the built-in procedural human.
- `HERMES_AVATAR_GLB_URL` remains available for operator-managed deployments.
- Three.js and `GLTFLoader` are still lazy-loaded through Plugin SDK 1.2; no CDN
  or new npm dependency is introduced.
- v0.4 adds a small responsive stylesheet layer so avatar-management buttons
  wrap safely on phones without changing the chat composer's layout contract.

## Architecture

```text
DigitalHumanPage (React composition root)
        |
        +-- HermesAvatarClient ---------> /api/plugins/hermes-avatar/chat
        |
        +-- AvatarModelStore
        |       +-- PUT    /api/plugins/hermes-avatar/avatar-model
        |       +-- GET    /api/plugins/hermes-avatar/avatar-model
        |       +-- DELETE /api/plugins/hermes-avatar/avatar-model
        |       +-- SDK.authedFetch -> Blob URL
        |
        +-- BrowserSpeechInput ---------> Web Speech Recognition
        |
        +-- BrowserSpeechOutput --------> Web Speech Synthesis
                    |
                    +-- VisemeMapper ---> open / round / wide / jaw
        |
        +-- AvatarController -----------> facial / state channels
                    |
                    +-- ThreeAvatarRenderer
                             |
                             +-- GLTFLoader -> GLB + Morph Targets
                             |
                             +-- procedural Three.js fallback

Hermes Plugin SDK 1.2
        |
        +-- graphics.loadThreeRuntime()
                +-- import("three")
                +-- import("three/examples/jsm/loaders/GLTFLoader.js")
```

### SOLID mapping

- **Single Responsibility**: Hermes transport, avatar storage, speech input,
  speech output, viseme mapping, facial state, UI composition, and Three.js
  rendering have separate classes/ports.
- **Open/Closed**: a Ready Player Me/custom GLB or a future TTS provider can be
  swapped without changing the Hermes chat transport.
- **Liskov Substitution**: the renderer receives renderer-independent facial
  signals and keeps the small lifecycle surface `init`, `setMode`, `destroy`.
- **Interface Segregation**: ordinary dashboard plugins never initialize
  Three.js; 3D code asks only for the optional graphics runtime.
- **Dependency Inversion**: browser code depends on the Dashboard SDK and the
  plugin API rather than provider globals, filesystem paths, or exposed AI
  credentials.

## Load a GLB avatar from the UI

1. Open **Digital Human**.
2. Press **LOAD GLB**.
3. Select a `.glb` file up to 25 MB.
4. After validation, Hermes stores it and reloads the renderer automatically.
5. Press **REMOVE GLB** to return to the configured/procedural avatar.

The storage location is resolved with `get_process_hermes_home()` so it follows
Hermes' real process profile on Railway, Linux, macOS, and Windows rather than
assuming a hard-coded `~/.hermes` path.

## Configure a deployment-managed GLB

The UI upload is optional. Operators can still configure a model URL:

```bash
HERMES_AVATAR_GLB_URL=https://assets.example.com/hermes-avatar.glb
```

A true same-origin path is also accepted:

```bash
HERMES_AVATAR_GLB_URL=/dashboard-plugins/hermes-avatar/assets/avatar.glb
```

The backend accepts explicit `https://` URLs or a single-leading-slash
same-origin path. Protocol-relative values such as `//host/avatar.glb`,
backslash-normalized variants, plain HTTP, and malformed HTTPS URLs are
rejected. Remote models must permit browser CORS access.

An uploaded model takes precedence. Removing it reveals the configured model
again; if neither exists, the local procedural human is used.

## Morph target compatibility

The renderer discovers morph dictionaries on every mesh and recognizes common
ARKit / Ready Player Me names including:

- `eyeBlinkLeft`, `eyeBlinkRight`
- `jawOpen`, `mouthOpen`, `viseme_aa`
- `mouthFunnel`, `mouthPucker`, `viseme_O`, `viseme_U`
- `mouthStretchLeft`, `mouthStretchRight`, `viseme_E`, `viseme_I`
- `mouthSmileLeft`, `mouthSmileRight`, `mouthSmile`
- `browInnerUp`, `browOuterUpLeft`, `browOuterUpRight`

Names are normalized for case and punctuation. If a GLB includes animation
clips, an idle/breathing-looking clip is preferred and otherwise the first clip
is played.

## Human and Hologram modes

Both modes use the same scene and facial rig. Human mode restores the model's
materials. Hologram mode applies cyan emissive/transparency treatment without
changing conversation, speech, or morph logic. Pointer movement drives subtle
head pose; the procedural fallback also moves the eyes.

## Hermes connection

The backend first uses Hermes' existing OpenAI-compatible Responses API:

```text
POST http://127.0.0.1:8642/v1/responses
```

With `API_SERVER_KEY` configured, Digital Human uses a named server-side
conversation. If that API server is unavailable, the existing in-process
fallback remains available. Provider credentials never enter browser JavaScript.

## Voice and lip sync

`VisemeMapper` translates speech-boundary characters into independent `open`,
`round`, `wide`, and `jaw` channels for Arabic and English. Browsers without
useful boundary events use a natural cadence while speech is active.

Those channels are translated into whatever compatible morph targets the GLB
contains. A future ElevenLabs/Google/alignment adapter can therefore provide
precise phoneme timing without rewriting Hermes transport or the 3D renderer.

## Runtime files

```text
dashboard/
├── manifest.json
├── plugin_api.py
└── dist/
    ├── avatar-v4.js
    ├── avatar-v4.css
    ├── three-avatar-renderer.js
    └── realistic.css
```

`avatar-v4.css` imports the established `realistic.css` visual contract and
adds only the v0.4 avatar-management responsive overrides. Superseded v0.2/v0.3
JavaScript entries are removed.

## Validation

The feature has a dedicated smoke-test module:

```text
tests/hermes_cli/test_digital_human_plugin.py
```

It checks the manifest/runtime contract, responsive v0.4 stylesheet layer,
lazy Three.js SDK boundary, morph mapping markers, safe configured-URL
validation, a real minimal GLB upload/replace/get/delete lifecycle in an
isolated `HERMES_HOME`, and rejection of non-GLB data.

Useful direct checks:

```bash
node --check plugins/hermes-avatar/dashboard/dist/avatar-v4.js
node --check plugins/hermes-avatar/dashboard/dist/three-avatar-renderer.js
python -m py_compile plugins/hermes-avatar/dashboard/plugin_api.py
python -m json.tool plugins/hermes-avatar/dashboard/manifest.json >/dev/null
pytest -q tests/hermes_cli/test_digital_human_plugin.py
```
