# Hermes Digital Human

A bundled Hermes Dashboard plugin that adds a responsive, voice-enabled 3D
digital-human interface while keeping chat, speech, facial state, and rendering
as separate responsibilities.

## Version 0.3.0

Digital Human v0.3 adds a real GLB/GLTF renderer path on top of the v0.2 voice
and facial-state work:

- Three.js is loaded lazily through the Hermes Dashboard Plugin SDK.
- `GLTFLoader` loads a configured GLB character without a CDN dependency.
- Ready Player Me/custom GLB morph targets are discovered at runtime.
- Common ARKit/Ready Player Me targets are mapped for blink, jaw, mouth round,
  mouth wide, smile, brow movement, and viseme-style articulation.
- Embedded idle/breathing animation clips are used when a GLB provides them.
- Head pose follows pointer movement when a head object is discoverable.
- Human and Hologram modes work through the same renderer adapter.
- If the GLB is absent or fails to load, a local Three.js procedural human is
  built automatically so chat and voice remain usable.
- Browser speech recognition, Arabic/English TTS, text input, Hermes sessions,
  and the server-side AI bridge remain independent of the 3D provider.

## Architecture

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
                    +-- ThreeAvatarRenderer
                             |
                             +-- GLTFLoader -> configured GLB + Morph Targets
                             |
                             +-- procedural Three.js fallback

Hermes Plugin SDK 1.2
        |
        +-- graphics.loadThreeRuntime()
                +-- import("three")
                +-- import("three/examples/jsm/loaders/GLTFLoader.js")
```

### SOLID mapping

- **Single Responsibility**: AI transport, speech input, speech output, viseme
  mapping, facial state, React composition, and Three.js rendering are separate
  classes/modules.
- **Open/Closed**: GLB models and future TTS providers can be swapped without
  modifying the Hermes chat client.
- **Liskov Substitution**: the renderer keeps a small lifecycle surface
  (`init`, `setMode`, `destroy`) and receives renderer-independent signals.
- **Interface Segregation**: 3D plugins request only the optional graphics
  runtime; ordinary dashboard plugins do not import or initialize Three.js.
- **Dependency Inversion**: the avatar consumes the host Plugin SDK and Hermes
  plugin API rather than provider globals or browser-exposed AI credentials.

## Configure a GLB avatar

Set this environment variable on the Hermes deployment:

```bash
HERMES_AVATAR_GLB_URL=https://assets.example.com/hermes-avatar.glb
```

A same-origin path is also supported, for example:

```bash
HERMES_AVATAR_GLB_URL=/dashboard-plugins/hermes-avatar/assets/avatar.glb
```

Only root-relative URLs and `https://` URLs are exposed by the backend. The
browser loads the asset directly; Hermes does not proxy arbitrary remote URLs.
For a remote model, its origin must permit browser CORS access.

When the variable is empty, invalid, or the model cannot be loaded, v0.3
automatically renders the local procedural human instead.

## Morph target compatibility

The renderer discovers morph dictionaries on every mesh and recognizes common
names including:

- `eyeBlinkLeft`, `eyeBlinkRight`
- `jawOpen`, `mouthOpen`, `viseme_aa`
- `mouthFunnel`, `mouthPucker`, `viseme_O`, `viseme_U`
- `mouthStretchLeft`, `mouthStretchRight`, `viseme_E`, `viseme_I`
- `mouthSmileLeft`, `mouthSmileRight`, `mouthSmile`
- `browInnerUp`, `browOuterUpLeft`, `browOuterUpRight`

Name matching is normalized for case and punctuation. A GLB can therefore come
from Ready Player Me or another character pipeline without coupling the chat
layer to a particular vendor.

## Hermes connection

The backend first uses Hermes' existing OpenAI-compatible Responses API:

```text
POST http://127.0.0.1:8642/v1/responses
```

With `API_SERVER_KEY` configured, Digital Human uses a named server-side
conversation. If the API server is unavailable, the existing in-process direct
fallback remains available. Provider credentials never enter browser JavaScript.

## Voice and lip sync

`VisemeMapper` turns speech-boundary characters into independent `open`,
`round`, `wide`, and `jaw` channels for Arabic and English. Browsers without
useful boundary timing use a natural cadence while speech is playing.

For a GLB, those same channels are translated into available morph targets.
This keeps the speech adapter replaceable: a future ElevenLabs/Google/alignment
provider can emit precise phoneme timing without changing Hermes transport or
3D model loading.

## Runtime files

```text
dashboard/
├── manifest.json
├── plugin_api.py
└── dist/
    ├── avatar-v3.js
    ├── three-avatar-renderer.js
    └── realistic.css
```

The v0.2 JavaScript renderer was removed after v0.3 became active. The v0.2
stylesheet remains because the v0.3 composition intentionally preserves the
same responsive UI contract.

## Validation

From the repository root:

```bash
node --check plugins/hermes-avatar/dashboard/dist/avatar-v3.js
node --check plugins/hermes-avatar/dashboard/dist/three-avatar-renderer.js
python -m py_compile plugins/hermes-avatar/dashboard/plugin_api.py
python -m json.tool plugins/hermes-avatar/dashboard/manifest.json >/dev/null
npm run --prefix web typecheck
```
