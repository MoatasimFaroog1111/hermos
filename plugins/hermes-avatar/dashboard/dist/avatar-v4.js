(function () {
  "use strict";

  const OWN_SCRIPT_URL = document.currentScript?.src || "";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  const REGISTRY = window.__HERMES_PLUGINS__;
  if (!SDK || !REGISTRY) return;

  const React = SDK.React;
  const h = React.createElement;
  const { useState, useEffect, useCallback, useMemo, useRef } = SDK.hooks;

  const STATES = Object.freeze({
    IDLE: "idle",
    LISTENING: "listening",
    THINKING: "thinking",
    SPEAKING: "speaking",
    ERROR: "error",
  });
  const LABELS = Object.freeze({
    idle: "Ready",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    error: "Needs attention",
  });
  const MODES = Object.freeze({ HUMAN: "human", HOLOGRAM: "hologram" });
  // Mirrors the entry script's own fail-open timeout (digital-human-entry.js).
  // The renderer module/WebGL init chain is otherwise unbounded: a stalled
  // chunk fetch or GLB download would leave the page stuck on "LOADING 3D"
  // forever with no way out. Chat and voice must stay usable either way.
  const RENDERER_INIT_TIMEOUT_MS = 12000;
  const DEFAULT_MAX_AVATAR_BYTES = 25 * 1024 * 1024;
  let rendererModulePromise = null;

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function createConversationId() {
    const key = "hermes.digitalHuman.conversation.v4";
    try {
      let id = sessionStorage.getItem(key);
      if (!id) {
        id = window.crypto?.randomUUID?.()
          || `human-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        sessionStorage.setItem(key, id);
      }
      return id;
    } catch {
      return `human-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
  }

  function rendererScriptUrl() {
    // Mirrors digital-human-entry.js's assetUrl(): resolve relative to our
    // own <script> tag (so a non-root dashboard base path still works) and
    // carry over the entry's manifest-version/cache-epoch query so a browser
    // or CDN can't keep serving a stale renderer after a deploy — this file
    // was previously loaded from a bare hardcoded path with no cache-busting
    // query at all, unlike every other asset in this plugin's chain.
    if (OWN_SCRIPT_URL) {
      try {
        const own = new URL(OWN_SCRIPT_URL, window.location.href);
        const resolved = new URL("three-avatar-renderer.js", own);
        if (own.search) resolved.search = own.search;
        return resolved.toString();
      } catch {
        // Fall through to the dashboard base path.
      }
    }
    const raw = String(window.__HERMES_BASE_PATH__ || "").trim();
    const base = raw ? `/${raw.replace(/^\/+|\/+$/g, "")}` : "";
    return `${base}/dashboard-plugins/hermes-avatar/dist/three-avatar-renderer.js`;
  }

  function loadRendererModule() {
    if (window.__HERMES_AVATAR_RENDERER__?.ThreeAvatarRenderer) {
      return Promise.resolve(window.__HERMES_AVATAR_RENDERER__);
    }
    if (rendererModulePromise) return rendererModulePromise;
    rendererModulePromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = rendererScriptUrl();
      script.async = true;
      script.onload = () => {
        if (window.__HERMES_AVATAR_RENDERER__?.ThreeAvatarRenderer) {
          resolve(window.__HERMES_AVATAR_RENDERER__);
        } else {
          reject(new Error("Avatar renderer module did not register."));
        }
      };
      script.onerror = () => reject(new Error("Unable to load avatar renderer module."));
      document.head.appendChild(script);
    });
    return rendererModulePromise;
  }

  class HermesAvatarClient {
    constructor(fetchJSON) {
      this.fetchJSON = fetchJSON;
    }

    send(message, conversationId) {
      return this.fetchJSON("/api/plugins/hermes-avatar/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, conversation_id: conversationId }),
      });
    }

    health() {
      return this.fetchJSON("/api/plugins/hermes-avatar/health");
    }
  }

  class AvatarModelStore {
    constructor(authedFetch) {
      this.authedFetch = authedFetch;
    }

    async responseJSON(response, fallbackMessage) {
      if (response.ok) return response.json();
      const raw = await response.text();
      let detail = raw;
      try {
        detail = JSON.parse(raw).detail || raw;
      } catch {
        // Keep the raw response body.
      }
      throw new Error(detail || fallbackMessage);
    }

    async upload(file) {
      const response = await this.authedFetch("/api/plugins/hermes-avatar/avatar-model", {
        method: "PUT",
        headers: { "Content-Type": "model/gltf-binary" },
        body: file,
      });
      return this.responseJSON(response, "Unable to upload the GLB avatar.");
    }

    async remove() {
      const response = await this.authedFetch("/api/plugins/hermes-avatar/avatar-model", {
        method: "DELETE",
      });
      return this.responseJSON(response, "Unable to remove the uploaded GLB avatar.");
    }

    async resolve(health) {
      const url = health?.avatar_model_url || "";
      if (!url) return { url: "", release: () => {} };

      const requiresAuth = Boolean(health?.avatar_model_requires_auth)
        || url.startsWith("/api/");
      if (!requiresAuth) return { url, release: () => {} };

      const response = await this.authedFetch(url);
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "Unable to load the stored GLB avatar.");
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      return {
        url: objectUrl,
        release: () => URL.revokeObjectURL(objectUrl),
      };
    }
  }

  class VisemeMapper {
    map(character) {
      const c = String(character || "").toLowerCase();
      if (/[mbp\u0645\u0628]/.test(c)) {
        return { open: 0.03, round: 0.02, wide: 0.12, jaw: 0.01 };
      }
      if (/[oquw\u0648]/.test(c)) {
        return { open: 0.40, round: 0.88, wide: 0.05, jaw: 0.28 };
      }
      if (/[eiy\u064a\u0649]/.test(c)) {
        return { open: 0.38, round: 0.04, wide: 0.88, jaw: 0.20 };
      }
      if (/[a\u0627\u0623\u0625]/.test(c)) {
        return { open: 0.78, round: 0.12, wide: 0.42, jaw: 0.54 };
      }
      if (/[fv\u0641]/.test(c)) {
        return { open: 0.16, round: 0.08, wide: 0.48, jaw: 0.08 };
      }
      if (/[sztdlnr\u0633\u0634\u062a\u062f\u0644\u0631]/.test(c)) {
        return { open: 0.28, round: 0.05, wide: 0.58, jaw: 0.14 };
      }
      return { open: 0.22, round: 0.08, wide: 0.34, jaw: 0.10 };
    }

    cadence(phase) {
      return {
        open: 0.24 + Math.abs(Math.sin(phase)) * 0.42,
        round: 0.10 + Math.abs(Math.sin(phase * 0.63)) * 0.24,
        wide: 0.28 + Math.abs(Math.cos(phase * 0.81)) * 0.28,
        jaw: 0.10 + Math.abs(Math.sin(phase)) * 0.27,
      };
    }
  }

  class BrowserSpeechOutput {
    constructor(visemes) {
      this.visemes = visemes;
      this.timer = null;
      this.utterance = null;
    }

    get supported() {
      return "speechSynthesis" in window;
    }

    stop() {
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
      if (this.supported) window.speechSynthesis.cancel();
      this.utterance = null;
    }

    chooseVoice(text) {
      if (!this.supported) return null;
      const arabic = /[\u0600-\u06ff]/.test(text);
      const prefix = arabic ? "ar" : "en";
      const voices = window.speechSynthesis.getVoices();
      return voices.find(voice =>
        voice.lang.toLowerCase().startsWith(prefix)
        && /google|microsoft|majed|hamed|samantha/i.test(voice.name)
      ) || voices.find(voice =>
        voice.lang.toLowerCase().startsWith(prefix)
      ) || voices[0] || null;
    }

    speak(text, events) {
      this.stop();
      if (!this.supported || !text.trim()) {
        events.onEnd();
        return;
      }

      const utterance = new SpeechSynthesisUtterance(text);
      const voice = this.chooseVoice(text);
      const arabic = /[\u0600-\u06ff]/.test(text);
      if (voice) utterance.voice = voice;
      utterance.lang = voice?.lang || (arabic ? "ar-SA" : "en-US");
      utterance.rate = arabic ? 0.98 : 1.02;
      utterance.pitch = 0.94;

      utterance.onstart = () => {
        events.onStart();
        let phase = 0;
        this.timer = setInterval(() => {
          phase += 0.72;
          events.onViseme(this.visemes.cadence(phase));
        }, 92);
      };
      utterance.onboundary = event => {
        const index = typeof event.charIndex === "number" ? event.charIndex : 0;
        events.onViseme(this.visemes.map(text[index] || text[index - 1] || ""));
      };
      utterance.onerror = event => {
        this.stop();
        if (event.error !== "canceled") events.onError(event.error || "speech_error");
      };
      utterance.onend = () => {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
        this.utterance = null;
        events.onViseme({ open: 0.03, round: 0, wide: 0.18, jaw: 0 });
        events.onEnd();
      };

      this.utterance = utterance;
      window.speechSynthesis.speak(utterance);
    }
  }

  class BrowserSpeechInput {
    constructor() {
      this.Ctor = window.SpeechRecognition || window.webkitSpeechRecognition || null;
      this.instance = null;
    }

    get supported() {
      return Boolean(this.Ctor);
    }

    stop() {
      if (this.instance) {
        try {
          this.instance.stop();
        } catch {
          // no-op
        }
      }
      this.instance = null;
    }

    listen({ onInterim }) {
      if (!this.Ctor) {
        return Promise.reject(new Error("Speech recognition is not supported in this browser."));
      }
      this.stop();

      return new Promise((resolve, reject) => {
        const recognition = new this.Ctor();
        this.instance = recognition;
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;
        recognition.lang = navigator.language || "en-US";
        let finalText = "";

        recognition.onresult = event => {
          let interim = "";
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const text = event.results[i][0]?.transcript || "";
            if (event.results[i].isFinal) finalText += text;
            else interim += text;
          }
          onInterim((finalText || interim).trim());
        };
        recognition.onerror = event => {
          this.instance = null;
          reject(new Error(event.error || "Microphone recognition failed."));
        };
        recognition.onend = () => {
          this.instance = null;
          if (finalText.trim()) resolve(finalText.trim());
          else reject(new Error("I did not catch any speech."));
        };
        recognition.start();
      });
    }
  }

  class AvatarController {
    constructor() {
      this.signals = {
        state: STATES.IDLE,
        blink: 0,
        mouthOpen: 0.03,
        mouthRound: 0,
        mouthWide: 0.18,
        jaw: 0,
        smile: 0.12,
        browLift: 0.05,
      };
      this.listeners = new Set();
      this.scheduleBlink();
    }

    subscribe(listener) {
      this.listeners.add(listener);
      listener(this.signals);
      return () => this.listeners.delete(listener);
    }

    emit() {
      for (const listener of this.listeners) listener(this.signals);
    }

    patch(patch) {
      this.signals = { ...this.signals, ...patch };
      this.emit();
    }

    setState(state) {
      this.patch({
        state,
        smile: state === STATES.SPEAKING ? 0.25 : state === STATES.IDLE ? 0.12 : 0.06,
        browLift: state === STATES.LISTENING ? 0.20 : state === STATES.THINKING ? 0.10 : 0.05,
      });
    }

    setViseme(value) {
      this.patch({
        mouthOpen: clamp(value.open ?? 0.03, 0.02, 0.95),
        mouthRound: clamp(value.round ?? 0, 0, 1),
        mouthWide: clamp(value.wide ?? 0.18, 0, 1),
        jaw: clamp(value.jaw ?? 0, 0, 0.72),
      });
    }

    scheduleBlink() {
      this.blinkTimer = setTimeout(() => {
        this.patch({ blink: 1 });
        setTimeout(() => this.patch({ blink: 0 }), 115);
        this.scheduleBlink();
      }, 2200 + Math.random() * 4200);
    }

    destroy() {
      if (this.blinkTimer) clearTimeout(this.blinkTimer);
      this.listeners.clear();
    }
  }

  function StatusPill({ state }) {
    return h(
      "div",
      { className: `dh2-status dh2-status--${state}`, "aria-live": "polite" },
      h("span", { className: "dh2-status__dot" }),
      h("span", null, LABELS[state] || state),
    );
  }

  function ModeSwitch({ mode, onChange }) {
    return h(
      "div",
      { className: "dh2-mode", role: "group", "aria-label": "Avatar visual mode" },
      h("button", {
        type: "button",
        className: mode === MODES.HUMAN ? "is-active" : "",
        onClick: () => onChange(MODES.HUMAN),
      }, "HUMAN"),
      h("button", {
        type: "button",
        className: mode === MODES.HOLOGRAM ? "is-active" : "",
        onClick: () => onChange(MODES.HOLOGRAM),
      }, "HOLOGRAM"),
    );
  }

  function AvatarControls({
    uploading,
    uploaded,
    maxBytes,
    onUpload,
    onRemove,
    onNewSession,
  }) {
    const inputRef = useRef(null);
    const chooseFile = () => inputRef.current?.click();
    const fileChanged = event => {
      const file = event.target.files?.[0] || null;
      event.target.value = "";
      if (file) onUpload(file);
    };
    const limitMb = Math.round((maxBytes || DEFAULT_MAX_AVATAR_BYTES) / 1024 / 1024);

    return h(
      "div",
      { className: "dh2-composer__actions", role: "group", "aria-label": "Avatar controls" },
      h("input", {
        ref: inputRef,
        type: "file",
        accept: ".glb,model/gltf-binary",
        onChange: fileChanged,
        style: { display: "none" },
        "aria-hidden": "true",
      }),
      h("button", {
        type: "button",
        className: "dh2-new",
        onClick: chooseFile,
        disabled: uploading,
        title: `Load a GLB avatar (max ${limitMb} MB)`,
      }, uploading ? "LOADING GLB" : "LOAD GLB"),
      uploaded && h("button", {
        type: "button",
        className: "dh2-new",
        onClick: onRemove,
        disabled: uploading,
      }, "REMOVE GLB"),
      h("button", {
        type: "button",
        className: "dh2-new",
        onClick: onNewSession,
        disabled: uploading,
      }, "NEW SESSION"),
    );
  }

  function AvatarStage({ controller, state, mode, onModeChange, modelUrl, modelConfigured }) {
    const canvasRef = useRef(null);
    const rendererRef = useRef(null);
    const [rendererStatus, setRendererStatus] = useState("loading");
    const [ready, setReady] = useState(true);

    useEffect(() => {
      if (!canvasRef.current) return undefined;
      let active = true;
      let renderer = null;
      let timedOut = false;

      const initTimeout = window.setTimeout(() => {
        timedOut = true;
        if (active) {
          console.warn(
            `[hermes-avatar] renderer init timed out after ${RENDERER_INIT_TIMEOUT_MS}ms; falling back to text/voice only`,
          );
          setReady(false);
          setRendererStatus("unavailable");
        }
        // In case init() lands after the timeout already gave up on it.
        renderer?.destroy();
      }, RENDERER_INIT_TIMEOUT_MS);

      loadRendererModule()
        .then(module => {
          if (!active || timedOut || !canvasRef.current) return undefined;
          renderer = new module.ThreeAvatarRenderer(canvasRef.current, controller, {
            mode,
            modelUrl,
            onStatus: status => {
              if (active && !timedOut) {
                setRendererStatus(status);
                setReady(true);
              }
            },
          });
          rendererRef.current = renderer;
          return renderer.init();
        })
        .then(() => {
          if (timedOut) renderer?.destroy();
          else window.clearTimeout(initTimeout);
        })
        .catch(error => {
          window.clearTimeout(initTimeout);
          console.warn("[hermes-avatar] renderer failed", error);
          if (active && !timedOut) {
            setReady(false);
            setRendererStatus("unavailable");
          }
        });

      return () => {
        active = false;
        window.clearTimeout(initTimeout);
        renderer?.destroy();
        if (rendererRef.current === renderer) rendererRef.current = null;
      };
    }, [controller, modelUrl]);

    useEffect(() => {
      rendererRef.current?.setMode(mode);
    }, [mode]);

    const labels = {
      glb: "GLB / MORPH TARGETS",
      "procedural-fallback": "GLB FALLBACK",
      procedural: "THREE PROCEDURAL",
      loading: "LOADING 3D",
      unavailable: "3D UNAVAILABLE",
    };
    const rendererLabel = labels[rendererStatus] || rendererStatus.toUpperCase();

    return h(
      "section",
      { className: `dh2-stage dh2-stage--${mode}`, "aria-label": "Interactive Hermes digital human" },
      h("div", { className: "dh2-stage__aurora" }),
      h("div", { className: "dh2-stage__grid" }),
      h("div", { className: "dh2-stage__ring dh2-stage__ring--a" }),
      h("div", { className: "dh2-stage__ring dh2-stage__ring--b" }),
      h("canvas", { ref: canvasRef, className: "dh2-stage__canvas", "aria-hidden": "true" }),
      !ready && h(
        "div",
        { className: "dh2-fallback" },
        h("strong", null, "3D unavailable"),
        h("span", null, "Chat and voice remain available."),
      ),
      h("div", { className: "dh2-stage__scan" }),
      h(
        "div",
        { className: "dh2-stage__top" },
        h(StatusPill, { state }),
        h(ModeSwitch, { mode, onChange: onModeChange }),
      ),
      h(
        "div",
        { className: "dh2-stage__caption" },
        h("span", { className: "dh2-kicker" }, `HERMES // DIGITAL HUMAN 04 // ${rendererLabel}`),
        h("strong", null, mode === MODES.HUMAN ? "Human Presence" : "Holographic Presence"),
        h("small", null, modelUrl
          ? "GLB renderer with morph-target mapping and automatic local fallback."
          : modelConfigured
            ? "Resolving your stored GLB avatar securely…"
            : "Load a GLB/Ready Player Me character, or use the built-in procedural human."),
      ),
    );
  }

  function MessageBubble({ item }) {
    return h(
      "article",
      { className: `dh2-message dh2-message--${item.role}` },
      h(
        "div",
        { className: "dh2-message__meta" },
        h("span", null, item.role === "user" ? "YOU" : "HERMES"),
        item.transport && h("span", null, item.transport),
      ),
      h("div", { className: "dh2-message__text", dir: "auto" }, item.text),
    );
  }

  function Transcript({ messages, thinking, endRef }) {
    return h(
      "div",
      { className: "dh2-transcript", role: "log", "aria-live": "polite" },
      messages.length === 0 && h(
        "div",
        { className: "dh2-empty" },
        h("div", { className: "dh2-empty__orb" }, "H"),
        h("strong", null, "Speak naturally with Hermes"),
        h("span", null, "Use text or microphone. Replies animate the face and play through your browser voice."),
      ),
      ...messages.map(item => h(MessageBubble, { item, key: item.id })),
      thinking && h(
        "div",
        { className: "dh2-thinking" },
        h("span"),
        h("span"),
        h("span"),
        h("em", null, "Hermes is thinking"),
      ),
      h("div", { ref: endRef }),
    );
  }

  function Composer(props) {
    const {
      value,
      onChange,
      onSubmit,
      onMic,
      micSupported,
      listening,
      busy,
      voiceEnabled,
      onToggleVoice,
      onStopVoice,
    } = props;

    const onKeyDown = event => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        onSubmit();
      }
    };

    return h(
      "div",
      { className: "dh2-composer" },
      h("textarea", {
        value,
        rows: 2,
        dir: "auto",
        placeholder: listening ? "Listening…" : "Talk to Hermes…",
        onChange: event => onChange(event.target.value),
        onKeyDown,
        disabled: busy || listening,
        "aria-label": "Message Hermes",
      }),
      h(
        "div",
        { className: "dh2-composer__actions" },
        h("button", {
          type: "button",
          className: `dh2-icon ${listening ? "is-live" : ""}`,
          onClick: onMic,
          disabled: !micSupported || busy,
          title: micSupported
            ? (listening ? "Stop listening" : "Use microphone")
            : "Speech recognition unavailable",
        }, listening ? "■" : "●"),
        h("button", {
          type: "button",
          className: `dh2-icon ${voiceEnabled ? "is-on" : ""}`,
          onClick: onToggleVoice,
        }, voiceEnabled ? "VOICE" : "MUTE"),
        h("button", {
          type: "button",
          className: "dh2-stop",
          onClick: onStopVoice,
        }, "STOP"),
        h("button", {
          type: "button",
          className: "dh2-send",
          onClick: onSubmit,
          disabled: busy || !value.trim(),
        }, busy ? "THINKING" : "SEND"),
      ),
    );
  }

  function FeatureStrip({ health, micSupported, voiceSupported, mode }) {
    const transport = health
      ? (health.api_server_configured ? "API SERVER" : "DIRECT FALLBACK")
      : "PROBING";
    const avatar = health?.avatar_uploaded
      ? "UPLOADED GLB"
      : health?.avatar_model_configured
        ? "CONFIGURED GLB"
        : "PROCEDURAL READY";

    return h(
      "div",
      { className: "dh2-features" },
      h("span", null, mode === MODES.HUMAN ? "HUMAN RENDER" : "HOLOGRAM RENDER"),
      h("span", null, avatar),
      h("span", null, "MORPH / VISEME FACE"),
      h("span", null, voiceSupported ? "TTS READY" : "TEXT ONLY"),
      h("span", null, micSupported ? "MIC READY" : "MIC UNSUPPORTED"),
      h("span", null, transport),
    );
  }

  function DigitalHumanPage() {
    const client = useMemo(() => new HermesAvatarClient(SDK.fetchJSON), []);
    const modelStore = useMemo(() => new AvatarModelStore(SDK.authedFetch), []);
    const visemes = useMemo(() => new VisemeMapper(), []);
    const speechOutput = useMemo(() => new BrowserSpeechOutput(visemes), [visemes]);
    const speechInput = useMemo(() => new BrowserSpeechInput(), []);
    const controller = useMemo(() => new AvatarController(), []);
    const conversationId = useMemo(createConversationId, []);

    const [state, setState] = useState(STATES.IDLE);
    const [mode, setMode] = useState(() => {
      try {
        return localStorage.getItem("hermes.digitalHuman.mode") || MODES.HUMAN;
      } catch {
        return MODES.HUMAN;
      }
    });
    const [input, setInput] = useState("");
    const [messages, setMessages] = useState([]);
    const [error, setError] = useState("");
    const [voiceEnabled, setVoiceEnabled] = useState(true);
    const [health, setHealth] = useState(null);
    const [resolvedModelUrl, setResolvedModelUrl] = useState("");
    const [avatarBusy, setAvatarBusy] = useState(false);
    const [interim, setInterim] = useState("");
    const endRef = useRef(null);

    const transition = useCallback(next => {
      setState(next);
      controller.setState(next);
    }, [controller]);

    const changeMode = useCallback(next => {
      setMode(next);
      try {
        localStorage.setItem("hermes.digitalHuman.mode", next);
      } catch {
        // ignore
      }
    }, []);

    useEffect(() => {
      client.health().then(setHealth).catch(() => setHealth(null));
      return () => {
        speechOutput.stop();
        speechInput.stop();
        controller.destroy();
      };
    }, [client, speechInput, speechOutput, controller]);

    useEffect(() => {
      let active = true;
      let release = () => {};
      setResolvedModelUrl("");

      if (!health?.avatar_model_url) return () => {};

      modelStore.resolve(health)
        .then(source => {
          if (!active) {
            source.release();
            return;
          }
          release = source.release;
          setResolvedModelUrl(source.url);
        })
        .catch(modelError => {
          if (!active) return;
          setResolvedModelUrl("");
          setError(modelError instanceof Error
            ? modelError.message
            : "Unable to resolve the avatar model.");
        });

      return () => {
        active = false;
        release();
      };
    }, [
      modelStore,
      health?.avatar_model_url,
      health?.avatar_model_requires_auth,
    ]);

    useEffect(() => {
      endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    }, [messages, state]);

    const speakReply = useCallback(text => {
      if (!voiceEnabled || !speechOutput.supported) {
        transition(STATES.IDLE);
        return;
      }
      speechOutput.speak(text, {
        onStart: () => transition(STATES.SPEAKING),
        onViseme: value => controller.setViseme(value),
        onEnd: () => {
          controller.setViseme({ open: 0.03, round: 0, wide: 0.18, jaw: 0 });
          transition(STATES.IDLE);
        },
        onError: () => {
          controller.setViseme({ open: 0.03, round: 0, wide: 0.18, jaw: 0 });
          transition(STATES.IDLE);
        },
      });
    }, [controller, speechOutput, transition, voiceEnabled]);

    const send = useCallback(async overrideText => {
      const text = (overrideText || input).trim();
      if (!text || state === STATES.THINKING) return;

      speechOutput.stop();
      controller.setViseme({ open: 0.03, round: 0, wide: 0.18, jaw: 0 });
      setError("");
      setInput("");
      setInterim("");
      setMessages(previous => [
        ...previous,
        { id: `u-${Date.now()}`, role: "user", text },
      ]);
      transition(STATES.THINKING);

      try {
        const response = await client.send(text, conversationId);
        const reply = String(response.reply || "").trim();
        if (!reply) throw new Error("Hermes returned an empty reply.");
        setMessages(previous => [
          ...previous,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            text: reply,
            transport: response.transport === "api-server" ? "AGENT" : "DIRECT",
          },
        ]);
        speakReply(reply);
      } catch (requestError) {
        setError(requestError instanceof Error
          ? requestError.message
          : "Unable to reach Hermes.");
        transition(STATES.ERROR);
      }
    }, [
      client,
      conversationId,
      controller,
      input,
      speakReply,
      speechOutput,
      state,
      transition,
    ]);

    const handleMic = useCallback(async () => {
      if (!speechInput.supported || state === STATES.THINKING) return;
      if (state === STATES.LISTENING) {
        speechInput.stop();
        transition(STATES.IDLE);
        return;
      }

      speechOutput.stop();
      setError("");
      setInterim("");
      transition(STATES.LISTENING);
      try {
        const text = await speechInput.listen({
          onInterim: value => {
            setInterim(value);
            setInput(value);
          },
        });
        setInput(text);
        transition(STATES.IDLE);
        await send(text);
      } catch (micError) {
        const message = micError instanceof Error
          ? micError.message
          : "Microphone recognition failed.";
        if (!/did not catch/i.test(message)) setError(message);
        transition(STATES.IDLE);
      }
    }, [send, speechInput, speechOutput, state, transition]);

    const handleAvatarUpload = useCallback(async file => {
      const maxBytes = health?.avatar_upload_max_bytes || DEFAULT_MAX_AVATAR_BYTES;
      if (!/\.glb$/i.test(file.name || "")) {
        setError("Choose a .glb avatar file.");
        return;
      }
      if (file.size > maxBytes) {
        setError(`Avatar is too large. Maximum size is ${Math.round(maxBytes / 1024 / 1024)} MB.`);
        return;
      }

      setAvatarBusy(true);
      setError("");
      try {
        const nextHealth = await modelStore.upload(file);
        setHealth(nextHealth);
      } catch (uploadError) {
        setError(uploadError instanceof Error
          ? uploadError.message
          : "Unable to upload the GLB avatar.");
      } finally {
        setAvatarBusy(false);
      }
    }, [health?.avatar_upload_max_bytes, modelStore]);

    const handleAvatarRemove = useCallback(async () => {
      setAvatarBusy(true);
      setError("");
      try {
        const nextHealth = await modelStore.remove();
        setHealth(nextHealth);
      } catch (removeError) {
        setError(removeError instanceof Error
          ? removeError.message
          : "Unable to remove the GLB avatar.");
      } finally {
        setAvatarBusy(false);
      }
    }, [modelStore]);

    const resetConversation = useCallback(() => {
      speechOutput.stop();
      speechInput.stop();
      setMessages([]);
      setError("");
      setInput("");
      setInterim("");
      transition(STATES.IDLE);
      try {
        sessionStorage.removeItem("hermes.digitalHuman.conversation.v4");
      } catch {
        // ignore
      }
      window.location.reload();
    }, [speechInput, speechOutput, transition]);

    return h(
      "main",
      { className: "dh2-page" },
      h(
        "header",
        { className: "dh2-header" },
        h(
          "div",
          null,
          h("div", { className: "dh2-kicker" }, "HERMES // INTERACTIVE DIGITAL HUMAN"),
          h("h1", null, "Digital Human"),
          h("p", null, "A face-to-face Hermes interface with uploadable GLB characters, morph targets, gaze, speech and text."),
        ),
        h(AvatarControls, {
          uploading: avatarBusy,
          uploaded: Boolean(health?.avatar_uploaded),
          maxBytes: health?.avatar_upload_max_bytes,
          onUpload: handleAvatarUpload,
          onRemove: handleAvatarRemove,
          onNewSession: resetConversation,
        }),
      ),
      h(FeatureStrip, {
        health,
        micSupported: speechInput.supported,
        voiceSupported: speechOutput.supported,
        mode,
      }),
      h(
        "div",
        { className: "dh2-workspace" },
        h(AvatarStage, {
          controller,
          state,
          mode,
          onModeChange: changeMode,
          modelUrl: resolvedModelUrl,
          modelConfigured: Boolean(health?.avatar_model_configured),
        }),
        h(
          "section",
          { className: "dh2-chat", "aria-label": "Conversation with Hermes" },
          h(
            "div",
            { className: "dh2-chat__header" },
            h(
              "div",
              null,
              h("span", { className: "dh2-kicker" }, "LIVE CHANNEL"),
              h("strong", { dir: "auto" },
                state === STATES.LISTENING && interim ? interim : "Conversation"),
            ),
            h(StatusPill, { state }),
          ),
          h(Transcript, {
            messages,
            thinking: state === STATES.THINKING,
            endRef,
          }),
          error && h(
            "div",
            { className: "dh2-error", role: "alert" },
            h(
              "div",
              null,
              h("strong", null, "Connection issue"),
              h("span", { dir: "auto" }, error),
            ),
            h("button", {
              type: "button",
              onClick: () => {
                setError("");
                if (state === STATES.ERROR) transition(STATES.IDLE);
              },
            }, "Dismiss"),
          ),
          h(Composer, {
            value: input,
            onChange: setInput,
            onSubmit: () => send(),
            onMic: handleMic,
            micSupported: speechInput.supported,
            listening: state === STATES.LISTENING,
            busy: state === STATES.THINKING,
            voiceEnabled,
            onToggleVoice: () => setVoiceEnabled(value => {
              if (value) {
                speechOutput.stop();
                controller.setViseme({ open: 0.03, round: 0, wide: 0.18, jaw: 0 });
                transition(STATES.IDLE);
              }
              return !value;
            }),
            onStopVoice: () => {
              speechOutput.stop();
              controller.setViseme({ open: 0.03, round: 0, wide: 0.18, jaw: 0 });
              transition(STATES.IDLE);
            },
          }),
        ),
      ),
      h(
        "footer",
        { className: "dh2-footer" },
        h("span", null,
          resolvedModelUrl ? "Renderer: Three.js GLB + fallback" : "Renderer: Three.js procedural"),
        h("span", null, "Face: Morph Targets + viseme + blink + gaze"),
        h("span", null, "Avatar: secure GLB upload or configured URL"),
        h("span", null, "Voice: browser STT/TTS adapter"),
        h("span", null, "AI: Hermes backend"),
      ),
    );
  }

  REGISTRY.register("hermes-avatar", DigitalHumanPage);
})();