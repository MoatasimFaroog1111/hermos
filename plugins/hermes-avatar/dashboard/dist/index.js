(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const REGISTRY = window.__HERMES_PLUGINS__;
  if (!SDK || !REGISTRY) return;

  const React = SDK.React;
  const h = React.createElement;
  const {
    useState,
    useEffect,
    useCallback,
    useMemo,
    useRef,
  } = SDK.hooks;

  const STATES = Object.freeze({
    IDLE: "idle",
    LISTENING: "listening",
    THINKING: "thinking",
    SPEAKING: "speaking",
    ERROR: "error",
  });

  const STATE_LABELS = Object.freeze({
    idle: "Ready",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    error: "Needs attention",
  });

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function createConversationId() {
    const key = "hermes.digitalHuman.conversation";
    try {
      let id = sessionStorage.getItem(key);
      if (!id) {
        id = (window.crypto && window.crypto.randomUUID)
          ? window.crypto.randomUUID()
          : `avatar-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        sessionStorage.setItem(key, id);
      }
      return id;
    } catch {
      return `avatar-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
  }

  // -------------------------------------------------------------------------
  // Transport service — Single Responsibility: Hermes chat only.
  // -------------------------------------------------------------------------
  class HermesAvatarClient {
    constructor(fetchJSON) {
      this.fetchJSON = fetchJSON;
    }

    async send(message, conversationId) {
      return this.fetchJSON("/api/plugins/hermes-avatar/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          conversation_id: conversationId,
        }),
      });
    }

    async health() {
      return this.fetchJSON("/api/plugins/hermes-avatar/health");
    }
  }

  // -------------------------------------------------------------------------
  // Voice output adapter — can be replaced by ElevenLabs/Google later.
  // -------------------------------------------------------------------------
  class BrowserSpeechOutput {
    constructor() {
      this.utterance = null;
      this.timer = null;
    }

    get supported() {
      return typeof window !== "undefined" && "speechSynthesis" in window;
    }

    stop() {
      if (this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
      if (this.supported) window.speechSynthesis.cancel();
      this.utterance = null;
    }

    chooseVoice(text) {
      if (!this.supported) return null;
      const isArabic = /[\u0600-\u06ff]/.test(text);
      const langPrefix = isArabic ? "ar" : "en";
      const voices = window.speechSynthesis.getVoices();
      return (
        voices.find((voice) => voice.lang.toLowerCase().startsWith(langPrefix) && /google|microsoft|samantha|majed|hamed/i.test(voice.name)) ||
        voices.find((voice) => voice.lang.toLowerCase().startsWith(langPrefix)) ||
        voices[0] ||
        null
      );
    }

    speak(text, events) {
      this.stop();
      if (!this.supported || !text.trim()) {
        events.onEnd();
        return;
      }

      const utterance = new SpeechSynthesisUtterance(text);
      const voice = this.chooseVoice(text);
      const isArabic = /[\u0600-\u06ff]/.test(text);
      if (voice) utterance.voice = voice;
      utterance.lang = voice ? voice.lang : (isArabic ? "ar-SA" : "en-US");
      utterance.rate = 1.02;
      utterance.pitch = 0.96;
      utterance.volume = 1;

      utterance.onstart = () => {
        events.onStart();
        let phase = 0;
        this.timer = setInterval(() => {
          phase += 0.7;
          const openness = 0.28 + Math.abs(Math.sin(phase)) * 0.48;
          events.onViseme(openness);
        }, 90);
      };
      utterance.onboundary = (event) => {
        const idx = typeof event.charIndex === "number" ? event.charIndex : 0;
        events.onViseme(mouthForCharacter(text[idx] || text[idx - 1] || ""));
      };
      utterance.onerror = (event) => {
        this.stop();
        if (event.error !== "canceled") events.onError(event.error || "speech_error");
      };
      utterance.onend = () => {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
        events.onViseme(0.04);
        this.utterance = null;
        events.onEnd();
      };

      this.utterance = utterance;
      window.speechSynthesis.speak(utterance);
    }
  }

  function mouthForCharacter(character) {
    const c = character.toLowerCase();
    if (/[mbp\u0645\u0628]/.test(c)) return 0.05;
    if (/[oouqw\u0648]/.test(c)) return 0.56;
    if (/[aeiy\u0627\u064a\u0649]/.test(c)) return 0.78;
    if (/[fvsztdlnr]/.test(c)) return 0.34;
    return 0.22;
  }

  // -------------------------------------------------------------------------
  // Voice input adapter — browser-native, with graceful unsupported fallback.
  // -------------------------------------------------------------------------
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
        try { this.instance.stop(); } catch { /* no-op */ }
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
        recognition.onresult = (event) => {
          let interim = "";
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const text = event.results[i][0] && event.results[i][0].transcript
              ? event.results[i][0].transcript
              : "";
            if (event.results[i].isFinal) finalText += text;
            else interim += text;
          }
          onInterim((finalText || interim).trim());
        };
        recognition.onerror = (event) => {
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

  // -------------------------------------------------------------------------
  // Avatar state controller — renderer-independent animation channels.
  // -------------------------------------------------------------------------
  class AvatarController {
    constructor() {
      this.signals = {
        state: STATES.IDLE,
        mouthOpen: 0.04,
        smile: 0.08,
        blink: 0,
      };
      this.listeners = new Set();
      this.blinkTimer = null;
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
        smile: state === STATES.SPEAKING ? 0.28 : state === STATES.IDLE ? 0.12 : 0.05,
      });
    }

    setMouth(value) {
      this.patch({ mouthOpen: clamp(value, 0.03, 0.95) });
    }

    scheduleBlink() {
      const delay = 2400 + Math.random() * 3600;
      this.blinkTimer = setTimeout(() => {
        this.patch({ blink: 1 });
        setTimeout(() => this.patch({ blink: 0 }), 130);
        this.scheduleBlink();
      }, delay);
    }

    destroy() {
      if (this.blinkTimer) clearTimeout(this.blinkTimer);
      this.listeners.clear();
    }
  }

  // -------------------------------------------------------------------------
  // Lightweight WebGL renderer. This is the visual adapter: swapping it for
  // Ready Player Me / GLTF + Three.js does not affect chat, voice or UI logic.
  // -------------------------------------------------------------------------
  class HologramRenderer {
    constructor(canvas, controller) {
      this.canvas = canvas;
      this.controller = controller;
      this.gl = canvas.getContext("webgl", {
        alpha: true,
        antialias: true,
        premultipliedAlpha: false,
      });
      this.raf = 0;
      this.startTime = performance.now();
      this.pointerYaw = 0;
      this.pointerPitch = 0;
      this.currentYaw = 0;
      this.currentPitch = 0;
      this.signals = controller.signals;
      this.unsubscribe = controller.subscribe((signals) => {
        this.signals = signals;
      });

      if (!this.gl) return;
      this.init();
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(canvas);
      this.onPointerMove = (event) => this.trackPointer(event);
      this.onPointerLeave = () => {
        this.pointerYaw = 0;
        this.pointerPitch = 0;
      };
      canvas.addEventListener("pointermove", this.onPointerMove);
      canvas.addEventListener("pointerleave", this.onPointerLeave);
      this.resize();
      this.render();
    }

    init() {
      const gl = this.gl;
      const vertexSource = `
        attribute vec3 aPosition;
        attribute vec3 aNormal;
        uniform vec3 uScale;
        uniform vec3 uOffset;
        uniform float uYaw;
        uniform float uPitch;
        uniform float uAspect;
        uniform float uTime;
        varying vec3 vNormal;
        varying vec3 vWorld;
        void main() {
          vec3 p = aPosition * uScale;
          float cy = cos(uYaw), sy = sin(uYaw);
          float cp = cos(uPitch), sp = sin(uPitch);
          p = vec3(cy * p.x + sy * p.z, p.y, -sy * p.x + cy * p.z);
          p = vec3(p.x, cp * p.y - sp * p.z, sp * p.y + cp * p.z);
          p += uOffset;
          float breath = sin(uTime * 1.45) * 0.008;
          p.y += breath * (1.0 + max(0.0, -p.y));
          vec3 n = aNormal;
          n = vec3(cy * n.x + sy * n.z, n.y, -sy * n.x + cy * n.z);
          n = vec3(n.x, cp * n.y - sp * n.z, sp * n.y + cp * n.z);
          vNormal = normalize(n);
          vWorld = p;
          float z = (p.z + 1.8) / 5.0;
          gl_Position = vec4(p.x / (1.75 * max(uAspect, 0.55)), p.y / 2.45, z, 1.0);
        }
      `;
      const fragmentSource = `
        precision mediump float;
        uniform vec3 uColor;
        uniform float uAlpha;
        uniform float uGlow;
        varying vec3 vNormal;
        varying vec3 vWorld;
        void main() {
          vec3 lightDir = normalize(vec3(-0.35, 0.55, 1.0));
          float diffuse = max(0.12, dot(normalize(vNormal), lightDir));
          float rim = pow(1.0 - abs(vNormal.z), 2.2);
          float scan = 0.88 + 0.12 * sin(vWorld.y * 95.0);
          vec3 color = uColor * (0.44 + diffuse * 0.55) + uColor * rim * uGlow;
          color *= scan;
          gl_FragColor = vec4(color, uAlpha * (0.72 + rim * 0.28));
        }
      `;

      this.program = this.createProgram(vertexSource, fragmentSource);
      this.locations = {
        position: gl.getAttribLocation(this.program, "aPosition"),
        normal: gl.getAttribLocation(this.program, "aNormal"),
        scale: gl.getUniformLocation(this.program, "uScale"),
        offset: gl.getUniformLocation(this.program, "uOffset"),
        yaw: gl.getUniformLocation(this.program, "uYaw"),
        pitch: gl.getUniformLocation(this.program, "uPitch"),
        aspect: gl.getUniformLocation(this.program, "uAspect"),
        time: gl.getUniformLocation(this.program, "uTime"),
        color: gl.getUniformLocation(this.program, "uColor"),
        alpha: gl.getUniformLocation(this.program, "uAlpha"),
        glow: gl.getUniformLocation(this.program, "uGlow"),
      };
      this.mesh = this.createSphere(34, 24);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
    }

    createShader(type, source) {
      const gl = this.gl;
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        const error = gl.getShaderInfoLog(shader) || "Shader compilation failed";
        gl.deleteShader(shader);
        throw new Error(error);
      }
      return shader;
    }

    createProgram(vertexSource, fragmentSource) {
      const gl = this.gl;
      const vertex = this.createShader(gl.VERTEX_SHADER, vertexSource);
      const fragment = this.createShader(gl.FRAGMENT_SHADER, fragmentSource);
      const program = gl.createProgram();
      gl.attachShader(program, vertex);
      gl.attachShader(program, fragment);
      gl.linkProgram(program);
      gl.deleteShader(vertex);
      gl.deleteShader(fragment);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(program) || "WebGL program link failed");
      }
      return program;
    }

    createSphere(longitude, latitude) {
      const positions = [];
      const normals = [];
      const indices = [];
      for (let y = 0; y <= latitude; y += 1) {
        const v = y / latitude;
        const phi = v * Math.PI;
        for (let x = 0; x <= longitude; x += 1) {
          const u = x / longitude;
          const theta = u * Math.PI * 2;
          const sx = Math.sin(phi) * Math.cos(theta);
          const sy = Math.cos(phi);
          const sz = Math.sin(phi) * Math.sin(theta);
          positions.push(sx, sy, sz);
          normals.push(sx, sy, sz);
        }
      }
      for (let y = 0; y < latitude; y += 1) {
        for (let x = 0; x < longitude; x += 1) {
          const a = y * (longitude + 1) + x;
          const b = a + longitude + 1;
          indices.push(a, b, a + 1, b, b + 1, a + 1);
        }
      }

      const gl = this.gl;
      const positionBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.STATIC_DRAW);

      const normalBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, normalBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(normals), gl.STATIC_DRAW);

      const indexBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);

      return { positionBuffer, normalBuffer, indexBuffer, count: indices.length };
    }

    trackPointer(event) {
      const rect = this.canvas.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
      const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
      this.pointerYaw = clamp(x * 0.22, -0.25, 0.25);
      this.pointerPitch = clamp(-y * 0.11, -0.12, 0.12);
    }

    resize() {
      if (!this.gl) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 1.8);
      const rect = this.canvas.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width * dpr));
      const height = Math.max(1, Math.round(rect.height * dpr));
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
      }
      this.gl.viewport(0, 0, width, height);
    }

    palette() {
      switch (this.signals.state) {
        case STATES.LISTENING: return [0.35, 0.93, 1.0];
        case STATES.THINKING: return [0.58, 0.50, 1.0];
        case STATES.SPEAKING: return [0.20, 1.0, 0.80];
        case STATES.ERROR: return [1.0, 0.34, 0.48];
        default: return [0.22, 0.86, 1.0];
      }
    }

    drawPart(scale, offset, color, alpha, glow, yaw, pitch) {
      const gl = this.gl;
      const loc = this.locations;
      gl.uniform3fv(loc.scale, scale);
      gl.uniform3fv(loc.offset, offset);
      gl.uniform1f(loc.yaw, yaw);
      gl.uniform1f(loc.pitch, pitch);
      gl.uniform3fv(loc.color, color);
      gl.uniform1f(loc.alpha, alpha);
      gl.uniform1f(loc.glow, glow);

      gl.bindBuffer(gl.ARRAY_BUFFER, this.mesh.positionBuffer);
      gl.enableVertexAttribArray(loc.position);
      gl.vertexAttribPointer(loc.position, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.mesh.normalBuffer);
      gl.enableVertexAttribArray(loc.normal);
      gl.vertexAttribPointer(loc.normal, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.mesh.indexBuffer);
      gl.drawElements(gl.TRIANGLES, this.mesh.count, gl.UNSIGNED_SHORT, 0);
    }

    render = () => {
      if (!this.gl) return;
      const gl = this.gl;
      const now = performance.now();
      const time = (now - this.startTime) / 1000;
      this.currentYaw += (this.pointerYaw - this.currentYaw) * 0.055;
      this.currentPitch += (this.pointerPitch - this.currentPitch) * 0.055;

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.useProgram(this.program);
      gl.uniform1f(this.locations.aspect, this.canvas.width / Math.max(this.canvas.height, 1));
      gl.uniform1f(this.locations.time, time);

      const color = this.palette();
      const yaw = this.currentYaw + Math.sin(time * 0.45) * 0.035;
      const pitch = this.currentPitch + Math.sin(time * 0.31) * 0.018;
      const blinkScale = this.signals.blink ? 0.06 : 1;
      const mouthOpen = this.signals.mouthOpen;
      const speakingPulse = this.signals.state === STATES.SPEAKING
        ? 1 + Math.sin(time * 8) * 0.025
        : 1;

      this.drawPart([0.82 * speakingPulse, 1.03, 0.72], [0, 0.48, 0], color, 0.43, 1.15, yaw, pitch);
      this.drawPart([0.31, 0.50, 0.31], [0, -0.60, -0.05], color, 0.30, 0.7, yaw * 0.55, pitch * 0.25);
      this.drawPart([1.34, 0.34, 0.50], [0, -1.12, -0.08], color, 0.24, 0.9, yaw * 0.18, 0);

      const eyeColor = [0.72, 1.0, 1.0];
      this.drawPart([0.105, 0.052 * blinkScale, 0.045], [-0.28, 0.72, 0.67], eyeColor, 0.96, 2.2, yaw, pitch);
      this.drawPart([0.105, 0.052 * blinkScale, 0.045], [0.28, 0.72, 0.67], eyeColor, 0.96, 2.2, yaw, pitch);

      this.drawPart([0.065, 0.15, 0.055], [0, 0.50, 0.71], color, 0.28, 0.45, yaw, pitch);
      const mouthColor = this.signals.state === STATES.SPEAKING
        ? [0.22, 1.0, 0.84]
        : [0.30, 0.84, 1.0];
      this.drawPart(
        [0.24 + this.signals.smile * 0.05, 0.028 + mouthOpen * 0.115, 0.038],
        [0, 0.22, 0.70],
        mouthColor,
        0.94,
        2.5,
        yaw,
        pitch,
      );

      this.raf = requestAnimationFrame(this.render);
    };

    destroy() {
      cancelAnimationFrame(this.raf);
      if (this.resizeObserver) this.resizeObserver.disconnect();
      if (this.unsubscribe) this.unsubscribe();
      this.canvas.removeEventListener("pointermove", this.onPointerMove);
      this.canvas.removeEventListener("pointerleave", this.onPointerLeave);
      if (this.gl) {
        if (this.mesh) {
          this.gl.deleteBuffer(this.mesh.positionBuffer);
          this.gl.deleteBuffer(this.mesh.normalBuffer);
          this.gl.deleteBuffer(this.mesh.indexBuffer);
        }
        if (this.program) this.gl.deleteProgram(this.program);
      }
    }
  }

  function StatusPill({ state }) {
    return h(
      "div",
      { className: `dh-status dh-status--${state}`, "aria-live": "polite" },
      h("span", { className: "dh-status__dot" }),
      h("span", null, STATE_LABELS[state] || state),
    );
  }

  function AvatarStage({ controller, state }) {
    const canvasRef = useRef(null);
    const [webglReady, setWebglReady] = useState(true);

    useEffect(() => {
      if (!canvasRef.current) return undefined;
      let renderer = null;
      try {
        renderer = new HologramRenderer(canvasRef.current, controller);
        if (!renderer.gl) setWebglReady(false);
      } catch (error) {
        console.warn("[hermes-avatar] WebGL renderer failed:", error);
        setWebglReady(false);
      }
      return () => {
        if (renderer) renderer.destroy();
      };
    }, [controller]);

    return h(
      "section",
      { className: "dh-stage", "aria-label": "Interactive Hermes digital human" },
      h("div", { className: "dh-stage__grid" }),
      h("div", { className: "dh-stage__halo dh-stage__halo--one" }),
      h("div", { className: "dh-stage__halo dh-stage__halo--two" }),
      h("div", { className: "dh-stage__beam" }),
      h("canvas", {
        ref: canvasRef,
        className: "dh-stage__canvas",
        "aria-hidden": "true",
      }),
      !webglReady && h(
        "div",
        { className: "dh-webgl-fallback" },
        h("div", { className: "dh-webgl-fallback__face" }, "H"),
        h("span", null, "WebGL unavailable — chat and voice are still active."),
      ),
      h("div", { className: "dh-stage__scanlines" }),
      h(
        "div",
        { className: "dh-stage__hud" },
        h(StatusPill, { state }),
        h("span", { className: "dh-stage__tag" }, "HERMES // AVATAR-01"),
      ),
      h(
        "div",
        { className: "dh-stage__caption" },
        h("strong", null, "Hermes Digital Human"),
        h("span", null, "Interactive neural interface"),
      ),
    );
  }

  function MessageBubble({ item }) {
    return h(
      "article",
      { className: `dh-message dh-message--${item.role}` },
      h(
        "div",
        { className: "dh-message__meta" },
        h("span", null, item.role === "user" ? "YOU" : "HERMES"),
        item.transport && h("span", { className: "dh-message__transport" }, item.transport),
      ),
      h("div", { className: "dh-message__text" }, item.text),
    );
  }

  function Transcript({ messages, thinking, endRef }) {
    return h(
      "div",
      { className: "dh-transcript", role: "log", "aria-live": "polite" },
      messages.length === 0 && h(
        "div",
        { className: "dh-empty" },
        h("div", { className: "dh-empty__glyph" }, "✦"),
        h("strong", null, "Start a conversation"),
        h("span", null, "Type a message or use the microphone. Hermes will reply here and through the avatar."),
      ),
      ...messages.map((item) => h(MessageBubble, { item, key: item.id })),
      thinking && h(
        "div",
        { className: "dh-thinking" },
        h("span"),
        h("span"),
        h("span"),
        h("em", null, "Hermes is thinking"),
      ),
      h("div", { ref: endRef }),
    );
  }

  function Composer({
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
  }) {
    const onKeyDown = (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        onSubmit();
      }
    };

    return h(
      "div",
      { className: "dh-composer" },
      h(
        "div",
        { className: "dh-composer__input-wrap" },
        h("textarea", {
          value,
          rows: 2,
          placeholder: listening ? "Listening…" : "Talk to Hermes…",
          onChange: (event) => onChange(event.target.value),
          onKeyDown,
          disabled: busy || listening,
          "aria-label": "Message Hermes",
        }),
        h(
          "button",
          {
            type: "button",
            className: `dh-icon-button ${listening ? "is-active" : ""}`,
            onClick: onMic,
            disabled: !micSupported || busy,
            title: micSupported ? "Speak" : "Speech recognition is not supported by this browser",
            "aria-label": listening ? "Stop listening" : "Start voice input",
          },
          listening ? "■" : "◉",
        ),
      ),
      h(
        "div",
        { className: "dh-composer__actions" },
        h(
          "button",
          {
            type: "button",
            className: `dh-voice-toggle ${voiceEnabled ? "is-on" : ""}`,
            onClick: onToggleVoice,
            title: "Toggle spoken replies",
          },
          h("span", null, voiceEnabled ? "VOICE ON" : "VOICE OFF"),
        ),
        h(
          "button",
          {
            type: "button",
            className: "dh-secondary-button",
            onClick: onStopVoice,
            title: "Stop speaking",
          },
          "STOP VOICE",
        ),
        h(
          "button",
          {
            type: "button",
            className: "dh-send-button",
            onClick: onSubmit,
            disabled: busy || listening || !value.trim(),
          },
          busy ? "WORKING…" : "SEND",
          h("span", { "aria-hidden": "true" }, "↗"),
        ),
      ),
    );
  }

  function FeatureStrip({ health, micSupported, voiceSupported }) {
    const transport = health
      ? (health.api_server_configured ? "API SERVER READY" : "DIRECT FALLBACK")
      : "PROBING HERMES";
    return h(
      "div",
      { className: "dh-feature-strip" },
      h("span", null, "3D WEBGL"),
      h("span", null, voiceSupported ? "TTS READY" : "TEXT ONLY"),
      h("span", null, micSupported ? "MIC READY" : "MIC UNSUPPORTED"),
      h("span", null, transport),
    );
  }

  function DigitalHumanPage() {
    const client = useMemo(() => new HermesAvatarClient(SDK.fetchJSON), []);
    const speechOutput = useMemo(() => new BrowserSpeechOutput(), []);
    const speechInput = useMemo(() => new BrowserSpeechInput(), []);
    const controller = useMemo(() => new AvatarController(), []);
    const conversationId = useMemo(createConversationId, []);

    const [state, setState] = useState(STATES.IDLE);
    const [input, setInput] = useState("");
    const [messages, setMessages] = useState([]);
    const [error, setError] = useState("");
    const [voiceEnabled, setVoiceEnabled] = useState(true);
    const [health, setHealth] = useState(null);
    const [interim, setInterim] = useState("");
    const endRef = useRef(null);

    const transition = useCallback((next) => {
      setState(next);
      controller.setState(next);
    }, [controller]);

    useEffect(() => {
      client.health().then(setHealth).catch(() => setHealth(null));
      return () => {
        speechOutput.stop();
        speechInput.stop();
        controller.destroy();
      };
    }, [client, speechInput, speechOutput, controller]);

    useEffect(() => {
      if (endRef.current) {
        endRef.current.scrollIntoView({ block: "end", behavior: "smooth" });
      }
    }, [messages, state]);

    const speakReply = useCallback((text) => {
      if (!voiceEnabled || !speechOutput.supported) {
        transition(STATES.IDLE);
        return;
      }
      speechOutput.speak(text, {
        onStart: () => transition(STATES.SPEAKING),
        onViseme: (value) => controller.setMouth(value),
        onEnd: () => {
          controller.setMouth(0.04);
          transition(STATES.IDLE);
        },
        onError: () => {
          controller.setMouth(0.04);
          transition(STATES.IDLE);
        },
      });
    }, [controller, speechOutput, transition, voiceEnabled]);

    const send = useCallback(async (overrideText) => {
      const message = (overrideText || input).trim();
      if (!message || state === STATES.THINKING) return;

      speechOutput.stop();
      controller.setMouth(0.04);
      setError("");
      setInput("");
      setInterim("");
      setMessages((prev) => [
        ...prev,
        { id: `u-${Date.now()}`, role: "user", text: message },
      ]);
      transition(STATES.THINKING);

      try {
        const response = await client.send(message, conversationId);
        const reply = String(response.reply || "").trim();
        if (!reply) throw new Error("Hermes returned an empty reply.");
        setMessages((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            text: reply,
            transport: response.transport === "api-server" ? "AGENT" : "DIRECT",
          },
        ]);
        speakReply(reply);
      } catch (requestError) {
        const messageText = requestError instanceof Error
          ? requestError.message
          : "Unable to reach Hermes.";
        setError(messageText);
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
          onInterim: (value) => {
            setInterim(value);
            setInput(value);
          },
        });
        setInput(text);
        transition(STATES.IDLE);
        await send(text);
      } catch (micError) {
        const messageText = micError instanceof Error
          ? micError.message
          : "Microphone recognition failed.";
        if (!/did not catch/i.test(messageText)) setError(messageText);
        transition(STATES.IDLE);
      }
    }, [send, speechInput, speechOutput, state, transition]);

    const resetConversation = useCallback(() => {
      speechOutput.stop();
      speechInput.stop();
      setMessages([]);
      setError("");
      setInput("");
      setInterim("");
      transition(STATES.IDLE);
      try {
        sessionStorage.removeItem("hermes.digitalHuman.conversation");
      } catch { /* ignore */ }
      window.location.reload();
    }, [speechInput, speechOutput, transition]);

    const busy = state === STATES.THINKING;

    return h(
      "main",
      { className: "dh-page" },
      h(
        "header",
        { className: "dh-header" },
        h(
          "div",
          null,
          h("div", { className: "dh-eyebrow" }, "HERMES // INTERACTIVE AVATAR"),
          h("h1", null, "Digital Human"),
          h("p", null, "A visual, voice-enabled interface to the same Hermes agent — models, memory and tools stay behind Hermes."),
        ),
        h(
          "button",
          { type: "button", className: "dh-reset", onClick: resetConversation },
          "NEW SESSION",
        ),
      ),
      h(FeatureStrip, {
        health,
        micSupported: speechInput.supported,
        voiceSupported: speechOutput.supported,
      }),
      h(
        "div",
        { className: "dh-workspace" },
        h(AvatarStage, { controller, state }),
        h(
          "section",
          { className: "dh-chat-panel", "aria-label": "Conversation with Hermes" },
          h(
            "div",
            { className: "dh-chat-panel__header" },
            h(
              "div",
              null,
              h("span", { className: "dh-panel-kicker" }, "LIVE CHANNEL"),
              h("strong", null, state === STATES.LISTENING && interim ? interim : "Conversation"),
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
            { className: "dh-error", role: "alert" },
            h("strong", null, "Connection issue"),
            h("span", null, error),
            h(
              "button",
              {
                type: "button",
                onClick: () => {
                  setError("");
                  transition(STATES.IDLE);
                },
              },
              "Dismiss",
            ),
          ),
          h(Composer, {
            value: input,
            onChange: setInput,
            onSubmit: () => send(),
            onMic: handleMic,
            micSupported: speechInput.supported,
            listening: state === STATES.LISTENING,
            busy,
            voiceEnabled,
            onToggleVoice: () => {
              setVoiceEnabled((value) => {
                if (value) {
                  speechOutput.stop();
                  controller.setMouth(0.04);
                  transition(STATES.IDLE);
                }
                return !value;
              });
            },
            onStopVoice: () => {
              speechOutput.stop();
              controller.setMouth(0.04);
              transition(STATES.IDLE);
            },
          }),
        ),
      ),
      h(
        "footer",
        { className: "dh-footer" },
        h("span", null, "Renderer: lightweight WebGL hologram"),
        h("span", null, "Voice: browser TTS/STT adapter"),
        h("span", null, "AI: Hermes backend"),
      ),
    );
  }

  REGISTRY.register("hermes-avatar", DigitalHumanPage);
})();