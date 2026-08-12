(function () {
  "use strict";

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

  const STATE_LABELS = Object.freeze({
    idle: "Ready",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    error: "Needs attention",
  });

  const MODES = Object.freeze({ HUMAN: "human", HOLOGRAM: "hologram" });

  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function lerp(a, b, t) { return a + (b - a) * t; }

  function createConversationId() {
    const key = "hermes.digitalHuman.conversation.v2";
    try {
      let id = sessionStorage.getItem(key);
      if (!id) {
        id = window.crypto?.randomUUID?.() || `human-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        sessionStorage.setItem(key, id);
      }
      return id;
    } catch {
      return `human-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
  }

  class HermesAvatarClient {
    constructor(fetchJSON) { this.fetchJSON = fetchJSON; }
    send(message, conversationId) {
      return this.fetchJSON("/api/plugins/hermes-avatar/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, conversation_id: conversationId }),
      });
    }
    health() { return this.fetchJSON("/api/plugins/hermes-avatar/health"); }
  }

  class VisemeMapper {
    map(character) {
      const c = String(character || "").toLowerCase();
      if (/[mbp\u0645\u0628]/.test(c)) return { open: 0.04, round: 0.05, wide: 0.22, jaw: 0.02 };
      if (/[oquw\u0648]/.test(c)) return { open: 0.42, round: 0.88, wide: 0.05, jaw: 0.28 };
      if (/[eiy\u064a\u0649]/.test(c)) return { open: 0.40, round: 0.04, wide: 0.86, jaw: 0.20 };
      if (/[a\u0627\u0623\u0625]/.test(c)) return { open: 0.76, round: 0.12, wide: 0.40, jaw: 0.52 };
      if (/[fv\u0641]/.test(c)) return { open: 0.18, round: 0.10, wide: 0.48, jaw: 0.08 };
      if (/[sztdlnr\u0633\u0634\u062a\u062f\u0644\u0631]/.test(c)) return { open: 0.28, round: 0.06, wide: 0.58, jaw: 0.14 };
      return { open: 0.22, round: 0.08, wide: 0.36, jaw: 0.10 };
    }

    cadence(phase) {
      return {
        open: 0.24 + Math.abs(Math.sin(phase)) * 0.42,
        round: 0.12 + Math.abs(Math.sin(phase * 0.63)) * 0.24,
        wide: 0.30 + Math.abs(Math.cos(phase * 0.81)) * 0.25,
        jaw: 0.10 + Math.abs(Math.sin(phase)) * 0.26,
      };
    }
  }

  class BrowserSpeechOutput {
    constructor(visemes) {
      this.visemes = visemes;
      this.utterance = null;
      this.timer = null;
    }

    get supported() { return "speechSynthesis" in window; }

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
      return voices.find(v => v.lang.toLowerCase().startsWith(prefix) && /google|microsoft|majed|hamed|samantha/i.test(v.name))
        || voices.find(v => v.lang.toLowerCase().startsWith(prefix))
        || voices[0]
        || null;
    }

    speak(text, events) {
      this.stop();
      if (!this.supported || !text.trim()) { events.onEnd(); return; }

      const u = new SpeechSynthesisUtterance(text);
      const voice = this.chooseVoice(text);
      const arabic = /[\u0600-\u06ff]/.test(text);
      if (voice) u.voice = voice;
      u.lang = voice?.lang || (arabic ? "ar-SA" : "en-US");
      u.rate = arabic ? 0.98 : 1.02;
      u.pitch = 0.94;
      u.volume = 1;

      u.onstart = () => {
        events.onStart();
        let phase = 0;
        this.timer = setInterval(() => {
          phase += 0.72;
          events.onViseme(this.visemes.cadence(phase));
        }, 92);
      };
      u.onboundary = e => {
        const i = typeof e.charIndex === "number" ? e.charIndex : 0;
        events.onViseme(this.visemes.map(text[i] || text[i - 1] || ""));
      };
      u.onerror = e => {
        this.stop();
        if (e.error !== "canceled") events.onError(e.error || "speech_error");
      };
      u.onend = () => {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
        this.utterance = null;
        events.onViseme({ open: 0.03, round: 0, wide: 0.2, jaw: 0 });
        events.onEnd();
      };

      this.utterance = u;
      window.speechSynthesis.speak(u);
    }
  }

  class BrowserSpeechInput {
    constructor() {
      this.Ctor = window.SpeechRecognition || window.webkitSpeechRecognition || null;
      this.instance = null;
    }
    get supported() { return Boolean(this.Ctor); }
    stop() {
      if (this.instance) {
        try { this.instance.stop(); } catch { /* noop */ }
      }
      this.instance = null;
    }
    listen({ onInterim }) {
      if (!this.Ctor) return Promise.reject(new Error("Speech recognition is not supported in this browser."));
      this.stop();
      return new Promise((resolve, reject) => {
        const r = new this.Ctor();
        this.instance = r;
        r.continuous = false;
        r.interimResults = true;
        r.maxAlternatives = 1;
        r.lang = navigator.language || "en-US";
        let finalText = "";
        r.onresult = event => {
          let interim = "";
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const t = event.results[i][0]?.transcript || "";
            if (event.results[i].isFinal) finalText += t;
            else interim += t;
          }
          onInterim((finalText || interim).trim());
        };
        r.onerror = event => {
          this.instance = null;
          reject(new Error(event.error || "Microphone recognition failed."));
        };
        r.onend = () => {
          this.instance = null;
          if (finalText.trim()) resolve(finalText.trim());
          else reject(new Error("I did not catch any speech."));
        };
        r.start();
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
        mouthWide: 0.20,
        jaw: 0,
        smile: 0.12,
        browLift: 0.05,
      };
      this.listeners = new Set();
      this.blinkTimer = null;
      this.scheduleBlink();
    }
    subscribe(fn) { this.listeners.add(fn); fn(this.signals); return () => this.listeners.delete(fn); }
    emit() { for (const fn of this.listeners) fn(this.signals); }
    patch(p) { this.signals = { ...this.signals, ...p }; this.emit(); }
    setState(state) {
      this.patch({
        state,
        smile: state === STATES.SPEAKING ? 0.24 : state === STATES.IDLE ? 0.12 : 0.06,
        browLift: state === STATES.LISTENING ? 0.20 : state === STATES.THINKING ? 0.10 : 0.05,
      });
    }
    setViseme(v) {
      this.patch({
        mouthOpen: clamp(v.open ?? 0.03, 0.02, 0.95),
        mouthRound: clamp(v.round ?? 0, 0, 1),
        mouthWide: clamp(v.wide ?? 0.20, 0, 1),
        jaw: clamp(v.jaw ?? 0, 0, 0.7),
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

  class DigitalHumanRenderer {
    constructor(canvas, controller, mode) {
      this.canvas = canvas;
      this.controller = controller;
      this.mode = mode;
      this.gl = canvas.getContext("webgl", {
        alpha: true, antialias: true, premultipliedAlpha: false,
      });
      this.pointerYaw = 0;
      this.pointerPitch = 0;
      this.currentYaw = 0;
      this.currentPitch = 0;
      this.startTime = performance.now();
      this.signals = controller.signals;
      this.unsubscribe = controller.subscribe(s => { this.signals = s; });
      this.reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches || false;
      if (!this.gl) return;
      this.init();
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(canvas);
      this.onPointerMove = e => this.trackPointer(e);
      this.onPointerLeave = () => { this.pointerYaw = 0; this.pointerPitch = 0; };
      canvas.addEventListener("pointermove", this.onPointerMove);
      canvas.addEventListener("pointerleave", this.onPointerLeave);
      this.resize();
      this.render();
    }

    setMode(mode) { this.mode = mode; }

    init() {
      const gl = this.gl;
      const vertex = `
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
          p = vec3(cy*p.x + sy*p.z, p.y, -sy*p.x + cy*p.z);
          p = vec3(p.x, cp*p.y - sp*p.z, sp*p.y + cp*p.z);
          p += uOffset;
          vWorld = p;
          vec3 n = aNormal;
          n = vec3(cy*n.x + sy*n.z, n.y, -sy*n.x + cy*n.z);
          n = vec3(n.x, cp*n.y - sp*n.z, sp*n.y + cp*n.z);
          vNormal = normalize(n);
          float z = (p.z + 2.3) / 6.2;
          gl_Position = vec4(p.x / (1.72 * max(uAspect, 0.58)), p.y / 2.60, z, 1.0);
        }`;
      const fragment = `
        precision mediump float;
        uniform vec3 uColor;
        uniform float uAlpha;
        uniform float uMetallic;
        uniform float uGlow;
        uniform float uHologram;
        varying vec3 vNormal;
        varying vec3 vWorld;
        void main() {
          vec3 n = normalize(vNormal);
          vec3 key = normalize(vec3(-0.55, 0.72, 1.0));
          vec3 fill = normalize(vec3(0.68, 0.18, 0.80));
          float d1 = max(0.0, dot(n, key));
          float d2 = max(0.0, dot(n, fill));
          float rim = pow(1.0 - abs(n.z), 2.5);
          float spec = pow(max(0.0, dot(reflect(-key, n), vec3(0.0, 0.0, 1.0))), 24.0);
          float scan = mix(1.0, 0.88 + 0.12*sin(vWorld.y*105.0), uHologram);
          vec3 lit = uColor * (0.34 + d1*0.58 + d2*0.16);
          lit += vec3(1.0) * spec * (0.08 + uMetallic*0.45);
          lit += uColor * rim * uGlow;
          lit *= scan;
          gl_FragColor = vec4(lit, uAlpha * mix(1.0, 0.78 + rim*0.22, uHologram));
        }`;
      this.program = this.createProgram(vertex, fragment);
      this.loc = {
        pos: gl.getAttribLocation(this.program, "aPosition"),
        normal: gl.getAttribLocation(this.program, "aNormal"),
        scale: gl.getUniformLocation(this.program, "uScale"),
        offset: gl.getUniformLocation(this.program, "uOffset"),
        yaw: gl.getUniformLocation(this.program, "uYaw"),
        pitch: gl.getUniformLocation(this.program, "uPitch"),
        aspect: gl.getUniformLocation(this.program, "uAspect"),
        time: gl.getUniformLocation(this.program, "uTime"),
        color: gl.getUniformLocation(this.program, "uColor"),
        alpha: gl.getUniformLocation(this.program, "uAlpha"),
        metallic: gl.getUniformLocation(this.program, "uMetallic"),
        glow: gl.getUniformLocation(this.program, "uGlow"),
        hologram: gl.getUniformLocation(this.program, "uHologram"),
      };
      this.mesh = this.createSphere(42, 30);
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
        const err = gl.getShaderInfoLog(shader) || "Shader compilation failed";
        gl.deleteShader(shader);
        throw new Error(err);
      }
      return shader;
    }

    createProgram(vs, fs) {
      const gl = this.gl;
      const v = this.createShader(gl.VERTEX_SHADER, vs);
      const f = this.createShader(gl.FRAGMENT_SHADER, fs);
      const p = gl.createProgram();
      gl.attachShader(p, v); gl.attachShader(p, f); gl.linkProgram(p);
      gl.deleteShader(v); gl.deleteShader(f);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(p) || "WebGL link failed");
      }
      return p;
    }

    createSphere(longitude, latitude) {
      const positions = [], normals = [], indices = [];
      for (let y = 0; y <= latitude; y += 1) {
        const phi = (y / latitude) * Math.PI;
        for (let x = 0; x <= longitude; x += 1) {
          const theta = (x / longitude) * Math.PI * 2;
          const sx = Math.sin(phi) * Math.cos(theta);
          const sy = Math.cos(phi);
          const sz = Math.sin(phi) * Math.sin(theta);
          positions.push(sx, sy, sz); normals.push(sx, sy, sz);
        }
      }
      for (let y = 0; y < latitude; y += 1) {
        for (let x = 0; x < longitude; x += 1) {
          const a = y * (longitude + 1) + x, b = a + longitude + 1;
          indices.push(a, b, a + 1, b, b + 1, a + 1);
        }
      }
      const gl = this.gl;
      const pb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, pb);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.STATIC_DRAW);
      const nb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, nb);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(normals), gl.STATIC_DRAW);
      const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);
      return { pb, nb, ib, count: indices.length };
    }

    trackPointer(e) {
      const r = this.canvas.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width - 0.5) * 2;
      const y = ((e.clientY - r.top) / r.height - 0.5) * 2;
      this.pointerYaw = clamp(x * 0.24, -0.27, 0.27);
      this.pointerPitch = clamp(-y * 0.11, -0.13, 0.13);
    }

    resize() {
      if (!this.gl) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 1.7);
      const r = this.canvas.getBoundingClientRect();
      const w = Math.max(1, Math.round(r.width * dpr));
      const hgt = Math.max(1, Math.round(r.height * dpr));
      if (this.canvas.width !== w || this.canvas.height !== hgt) {
        this.canvas.width = w; this.canvas.height = hgt;
      }
      this.gl.viewport(0, 0, w, hgt);
    }

    rotateLocal(local, center, yaw, pitch) {
      let [x, y, z] = local;
      const cy = Math.cos(yaw), sy = Math.sin(yaw);
      const cp = Math.cos(pitch), sp = Math.sin(pitch);
      const x1 = cy*x + sy*z, z1 = -sy*x + cy*z;
      const y2 = cp*y - sp*z1, z2 = sp*y + cp*z1;
      return [center[0] + x1, center[1] + y2, center[2] + z2];
    }

    draw(scale, offset, color, alpha = 1, metallic = 0, glow = 0, yaw = 0, pitch = 0) {
      const gl = this.gl, l = this.loc;
      gl.uniform3fv(l.scale, scale); gl.uniform3fv(l.offset, offset);
      gl.uniform1f(l.yaw, yaw); gl.uniform1f(l.pitch, pitch);
      gl.uniform3fv(l.color, color); gl.uniform1f(l.alpha, alpha);
      gl.uniform1f(l.metallic, metallic); gl.uniform1f(l.glow, glow);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.mesh.pb);
      gl.enableVertexAttribArray(l.pos); gl.vertexAttribPointer(l.pos, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.mesh.nb);
      gl.enableVertexAttribArray(l.normal); gl.vertexAttribPointer(l.normal, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.mesh.ib);
      gl.drawElements(gl.TRIANGLES, this.mesh.count, gl.UNSIGNED_SHORT, 0);
    }

    colors() {
      if (this.mode === MODES.HOLOGRAM) {
        return {
          skin: [0.19, 0.90, 1.00], skin2: [0.23, 1.00, 0.85], hair: [0.10, 0.55, 0.70],
          eye: [0.70, 1.00, 1.00], iris: [0.20, 1.00, 0.90], pupil: [0.02, 0.14, 0.18],
          lip: [0.30, 1.00, 0.88], mouth: [0.02, 0.12, 0.15], cloth: [0.14, 0.50, 0.68],
        };
      }
      return {
        skin: [0.67, 0.43, 0.32],
        skin2: [0.76, 0.52, 0.39],
        hair: [0.055, 0.045, 0.045],
        eye: [0.90, 0.92, 0.89],
        iris: [0.16, 0.34, 0.29],
        pupil: [0.015, 0.018, 0.018],
        lip: [0.50, 0.20, 0.19],
        mouth: [0.08, 0.025, 0.03],
        cloth: [0.035, 0.09, 0.14],
      };
    }

    render = () => {
      if (!this.gl) return;
      const gl = this.gl;
      const t = (performance.now() - this.startTime) / 1000;
      const motion = this.reducedMotion ? 0.25 : 1;
      this.currentYaw = lerp(this.currentYaw, this.pointerYaw, 0.055);
      this.currentPitch = lerp(this.currentPitch, this.pointerPitch, 0.055);
      const yaw = this.currentYaw + Math.sin(t * 0.45) * 0.024 * motion;
      const pitch = this.currentPitch + Math.sin(t * 0.31) * 0.010 * motion;
      const C = this.colors();
      const holo = this.mode === MODES.HOLOGRAM ? 1 : 0;
      const alpha = holo ? 0.68 : 1;

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.useProgram(this.program);
      gl.uniform1f(this.loc.aspect, this.canvas.width / Math.max(this.canvas.height, 1));
      gl.uniform1f(this.loc.time, t);
      gl.uniform1f(this.loc.hologram, holo);

      const breath = Math.sin(t * 1.35) * 0.012 * motion;
      this.draw([1.42 + breath, 0.50, 0.54], [0, -1.34, -0.12], C.cloth, alpha, 0.18, holo ? 0.9 : 0.03, yaw * 0.08, 0);
      this.draw([0.88, 0.56, 0.42], [0, -0.98, -0.02], C.cloth, alpha, 0.12, holo ? 0.8 : 0.02, yaw * 0.12, 0);
      this.draw([0.31, 0.47, 0.28], [0, -0.54, 0.00], C.skin, alpha, 0.03, holo ? 0.9 : 0.02, yaw * 0.45, pitch * 0.15);

      const headCenter = [0, 0.38 - this.signals.jaw * 0.035, 0.02];
      this.draw([0.72, 0.92, 0.66], headCenter, C.skin, alpha, 0.02, holo ? 1.1 : 0.02, yaw, pitch);
      this.draw([0.56, 0.44, 0.57], this.rotateLocal([0, -0.40, 0.16], headCenter, yaw, pitch), C.skin2, alpha, 0.02, holo ? 0.9 : 0.02, yaw, pitch);
      this.draw([0.24, 0.20, 0.16], this.rotateLocal([-0.36, -0.05, 0.52], headCenter, yaw, pitch), C.skin2, alpha, 0.01, 0, yaw, pitch);
      this.draw([0.24, 0.20, 0.16], this.rotateLocal([0.36, -0.05, 0.52], headCenter, yaw, pitch), C.skin2, alpha, 0.01, 0, yaw, pitch);
      this.draw([0.105, 0.20, 0.075], this.rotateLocal([-0.70, 0.01, 0.02], headCenter, yaw, pitch), C.skin, alpha, 0.01, 0, yaw, pitch);
      this.draw([0.105, 0.20, 0.075], this.rotateLocal([0.70, 0.01, 0.02], headCenter, yaw, pitch), C.skin, alpha, 0.01, 0, yaw, pitch);
      this.draw([0.74, 0.40, 0.67], this.rotateLocal([0, 0.67, -0.02], headCenter, yaw, pitch), C.hair, alpha, 0.05, holo ? 0.7 : 0.01, yaw, pitch);
      this.draw([0.17, 0.48, 0.20], this.rotateLocal([-0.60, 0.34, -0.12], headCenter, yaw, pitch), C.hair, alpha, 0.04, 0, yaw, pitch);
      this.draw([0.17, 0.48, 0.20], this.rotateLocal([0.60, 0.34, -0.12], headCenter, yaw, pitch), C.hair, alpha, 0.04, 0, yaw, pitch);

      const blink = this.signals.blink ? 0.07 : 1;
      const gazeX = clamp(this.currentYaw * 0.13, -0.045, 0.045);
      const gazeY = clamp(-this.currentPitch * 0.12, -0.025, 0.025);
      for (const side of [-1, 1]) {
        const eyeLocal = [side * 0.265, 0.18, 0.585];
        const eyePos = this.rotateLocal(eyeLocal, headCenter, yaw, pitch);
        this.draw([0.155, 0.080 * blink, 0.055], eyePos, C.eye, alpha, 0.02, holo ? 1.2 : 0.02, yaw, pitch);
        if (!this.signals.blink) {
          const irisPos = this.rotateLocal([eyeLocal[0] + gazeX, eyeLocal[1] + gazeY, 0.638], headCenter, yaw, pitch);
          this.draw([0.056, 0.056, 0.025], irisPos, C.iris, alpha, 0.05, holo ? 1.5 : 0.03, yaw, pitch);
          const pupilPos = this.rotateLocal([eyeLocal[0] + gazeX, eyeLocal[1] + gazeY, 0.657], headCenter, yaw, pitch);
          this.draw([0.024, 0.024, 0.014], pupilPos, C.pupil, alpha, 0.02, holo ? 1.5 : 0, yaw, pitch);
        }
        const browY = 0.37 + this.signals.browLift * 0.06;
        this.draw([0.19, 0.035, 0.035], this.rotateLocal([side * 0.28, browY, 0.57], headCenter, yaw, pitch), C.hair, alpha, 0.01, 0, yaw, pitch);
      }

      this.draw([0.080, 0.23, 0.075], this.rotateLocal([0, 0.00, 0.62], headCenter, yaw, pitch), C.skin2, alpha, 0.02, 0, yaw, pitch);
      this.draw([0.115, 0.085, 0.095], this.rotateLocal([0, -0.16, 0.68], headCenter, yaw, pitch), C.skin2, alpha, 0.02, 0, yaw, pitch);

      const open = this.signals.mouthOpen;
      const round = this.signals.mouthRound;
      const wide = this.signals.mouthWide;
      const mouthW = 0.20 + wide * 0.13 - round * 0.055 + this.signals.smile * 0.035;
      const mouthH = 0.018 + open * 0.105;
      const mouthCenter = this.rotateLocal([0, -0.34 - this.signals.jaw * 0.055, 0.625], headCenter, yaw, pitch);
      if (open > 0.08) this.draw([mouthW * 0.86, mouthH, 0.028], mouthCenter, C.mouth, alpha, 0, holo ? 1.0 : 0, yaw, pitch);
      const upper = this.rotateLocal([0, -0.31 - this.signals.jaw * 0.025, 0.651], headCenter, yaw, pitch);
      const lower = this.rotateLocal([0, -0.37 - this.signals.jaw * 0.075, 0.651], headCenter, yaw, pitch);
      this.draw([mouthW, 0.025 + open * 0.012, 0.026], upper, C.lip, alpha, 0.01, holo ? 1.1 : 0.01, yaw, pitch);
      this.draw([mouthW * (0.98 + round * 0.04), 0.028 + open * 0.020, 0.026], lower, C.lip, alpha, 0.01, holo ? 1.1 : 0.01, yaw, pitch);
      this.draw([0.22, 0.11, 0.10], this.rotateLocal([0, -0.56 - this.signals.jaw * 0.06, 0.46], headCenter, yaw, pitch), C.skin2, alpha, 0.01, 0, yaw, pitch);

      this.raf = requestAnimationFrame(this.render);
    };

    destroy() {
      cancelAnimationFrame(this.raf);
      this.resizeObserver?.disconnect();
      this.unsubscribe?.();
      this.canvas.removeEventListener("pointermove", this.onPointerMove);
      this.canvas.removeEventListener("pointerleave", this.onPointerLeave);
      if (this.gl) {
        if (this.mesh) {
          this.gl.deleteBuffer(this.mesh.pb); this.gl.deleteBuffer(this.mesh.nb); this.gl.deleteBuffer(this.mesh.ib);
        }
        if (this.program) this.gl.deleteProgram(this.program);
      }
    }
  }

  function StatusPill({ state }) {
    return h("div", { className: `dh2-status dh2-status--${state}`, "aria-live": "polite" },
      h("span", { className: "dh2-status__dot" }),
      h("span", null, STATE_LABELS[state] || state));
  }

  function ModeSwitch({ mode, onChange }) {
    return h("div", { className: "dh2-mode", role: "group", "aria-label": "Avatar visual mode" },
      h("button", { type: "button", className: mode === MODES.HUMAN ? "is-active" : "", onClick: () => onChange(MODES.HUMAN) }, "HUMAN"),
      h("button", { type: "button", className: mode === MODES.HOLOGRAM ? "is-active" : "", onClick: () => onChange(MODES.HOLOGRAM) }, "HOLOGRAM"));
  }

  function AvatarStage({ controller, state, mode, onModeChange }) {
    const canvasRef = useRef(null);
    const rendererRef = useRef(null);
    const [ready, setReady] = useState(true);

    useEffect(() => {
      if (!canvasRef.current) return undefined;
      try {
        rendererRef.current = new DigitalHumanRenderer(canvasRef.current, controller, mode);
        if (!rendererRef.current.gl) setReady(false);
      } catch (e) {
        console.warn("[hermes-avatar] renderer failed", e);
        setReady(false);
      }
      return () => rendererRef.current?.destroy();
    }, [controller]);

    useEffect(() => { rendererRef.current?.setMode(mode); }, [mode]);

    return h("section", { className: `dh2-stage dh2-stage--${mode}`, "aria-label": "Interactive Hermes digital human" },
      h("div", { className: "dh2-stage__aurora" }),
      h("div", { className: "dh2-stage__grid" }),
      h("div", { className: "dh2-stage__ring dh2-stage__ring--a" }),
      h("div", { className: "dh2-stage__ring dh2-stage__ring--b" }),
      h("canvas", { ref: canvasRef, className: "dh2-stage__canvas", "aria-hidden": "true" }),
      !ready && h("div", { className: "dh2-fallback" }, h("strong", null, "3D unavailable"), h("span", null, "Chat and voice remain available.")),
      h("div", { className: "dh2-stage__scan" }),
      h("div", { className: "dh2-stage__top" }, h(StatusPill, { state }), h(ModeSwitch, { mode, onChange: onModeChange })),
      h("div", { className: "dh2-stage__caption" },
        h("span", { className: "dh2-kicker" }, "HERMES // DIGITAL HUMAN 02"),
        h("strong", null, mode === MODES.HUMAN ? "Human Presence" : "Holographic Presence"),
        h("small", null, "Move your pointer to guide eye contact and head pose.")));
  }

  function MessageBubble({ item }) {
    return h("article", { className: `dh2-message dh2-message--${item.role}` },
      h("div", { className: "dh2-message__meta" },
        h("span", null, item.role === "user" ? "YOU" : "HERMES"),
        item.transport && h("span", null, item.transport)),
      h("div", { className: "dh2-message__text", dir: "auto" }, item.text));
  }

  function Transcript({ messages, thinking, endRef }) {
    return h("div", { className: "dh2-transcript", role: "log", "aria-live": "polite" },
      messages.length === 0 && h("div", { className: "dh2-empty" },
        h("div", { className: "dh2-empty__orb" }, "H"),
        h("strong", null, "Speak naturally with Hermes"),
        h("span", null, "Use text or microphone. Replies animate the face and play through your browser voice.")),
      ...messages.map(item => h(MessageBubble, { item, key: item.id })),
      thinking && h("div", { className: "dh2-thinking" },
        h("span"), h("span"), h("span"), h("em", null, "Hermes is thinking")),
      h("div", { ref: endRef }));
  }

  function Composer({ value, onChange, onSubmit, onMic, micSupported, listening, busy, voiceEnabled, onToggleVoice, onStopVoice }) {
    const onKeyDown = e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit(); }
    };
    return h("div", { className: "dh2-composer" },
      h("textarea", {
        value, rows: 2, dir: "auto",
        placeholder: listening ? "Listening…" : "Talk to Hermes…",
        onChange: e => onChange(e.target.value), onKeyDown,
        disabled: busy || listening, "aria-label": "Message Hermes",
      }),
      h("div", { className: "dh2-composer__actions" },
        h("button", {
          type: "button", className: `dh2-icon ${listening ? "is-live" : ""}`,
          onClick: onMic, disabled: !micSupported || busy,
          title: micSupported ? (listening ? "Stop listening" : "Use microphone") : "Speech recognition unavailable",
        }, listening ? "■" : "●"),
        h("button", {
          type: "button", className: `dh2-icon ${voiceEnabled ? "is-on" : ""}`,
          onClick: onToggleVoice, title: voiceEnabled ? "Disable voice" : "Enable voice",
        }, voiceEnabled ? "VOICE" : "MUTE"),
        h("button", { type: "button", className: "dh2-stop", onClick: onStopVoice }, "STOP"),
        h("button", { type: "button", className: "dh2-send", onClick: onSubmit, disabled: busy || !value.trim() }, busy ? "THINKING" : "SEND")));
  }

  function FeatureStrip({ health, micSupported, voiceSupported, mode }) {
    const transport = health ? (health.api_server_configured ? "API SERVER" : "DIRECT FALLBACK") : "PROBING";
    return h("div", { className: "dh2-features" },
      h("span", null, mode === MODES.HUMAN ? "HUMAN RENDER" : "HOLOGRAM RENDER"),
      h("span", null, "VISEME FACE"),
      h("span", null, voiceSupported ? "TTS READY" : "TEXT ONLY"),
      h("span", null, micSupported ? "MIC READY" : "MIC UNSUPPORTED"),
      h("span", null, transport));
  }

  function DigitalHumanPage() {
    const client = useMemo(() => new HermesAvatarClient(SDK.fetchJSON), []);
    const visemes = useMemo(() => new VisemeMapper(), []);
    const speechOutput = useMemo(() => new BrowserSpeechOutput(visemes), [visemes]);
    const speechInput = useMemo(() => new BrowserSpeechInput(), []);
    const controller = useMemo(() => new AvatarController(), []);
    const conversationId = useMemo(createConversationId, []);

    const [state, setState] = useState(STATES.IDLE);
    const [mode, setMode] = useState(() => {
      try { return localStorage.getItem("hermes.digitalHuman.mode") || MODES.HUMAN; }
      catch { return MODES.HUMAN; }
    });
    const [input, setInput] = useState("");
    const [messages, setMessages] = useState([]);
    const [error, setError] = useState("");
    const [voiceEnabled, setVoiceEnabled] = useState(true);
    const [health, setHealth] = useState(null);
    const [interim, setInterim] = useState("");
    const endRef = useRef(null);

    const transition = useCallback(next => {
      setState(next); controller.setState(next);
    }, [controller]);

    const changeMode = useCallback(next => {
      setMode(next);
      try { localStorage.setItem("hermes.digitalHuman.mode", next); } catch { /* ignore */ }
    }, []);

    useEffect(() => {
      client.health().then(setHealth).catch(() => setHealth(null));
      return () => { speechOutput.stop(); speechInput.stop(); controller.destroy(); };
    }, [client, speechInput, speechOutput, controller]);

    useEffect(() => {
      endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    }, [messages, state]);

    const speakReply = useCallback(text => {
      if (!voiceEnabled || !speechOutput.supported) { transition(STATES.IDLE); return; }
      speechOutput.speak(text, {
        onStart: () => transition(STATES.SPEAKING),
        onViseme: v => controller.setViseme(v),
        onEnd: () => { controller.setViseme({ open: 0.03, round: 0, wide: 0.2, jaw: 0 }); transition(STATES.IDLE); },
        onError: () => { controller.setViseme({ open: 0.03, round: 0, wide: 0.2, jaw: 0 }); transition(STATES.IDLE); },
      });
    }, [controller, speechOutput, transition, voiceEnabled]);

    const send = useCallback(async overrideText => {
      const text = (overrideText || input).trim();
      if (!text || state === STATES.THINKING) return;
      speechOutput.stop();
      controller.setViseme({ open: 0.03, round: 0, wide: 0.2, jaw: 0 });
      setError(""); setInput(""); setInterim("");
      setMessages(prev => [...prev, { id: `u-${Date.now()}`, role: "user", text }]);
      transition(STATES.THINKING);
      try {
        const response = await client.send(text, conversationId);
        const reply = String(response.reply || "").trim();
        if (!reply) throw new Error("Hermes returned an empty reply.");
        setMessages(prev => [...prev, {
          id: `a-${Date.now()}`, role: "assistant", text: reply,
          transport: response.transport === "api-server" ? "AGENT" : "DIRECT",
        }]);
        speakReply(reply);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unable to reach Hermes.");
        transition(STATES.ERROR);
      }
    }, [client, conversationId, controller, input, speakReply, speechOutput, state, transition]);

    const handleMic = useCallback(async () => {
      if (!speechInput.supported || state === STATES.THINKING) return;
      if (state === STATES.LISTENING) { speechInput.stop(); transition(STATES.IDLE); return; }
      speechOutput.stop(); setError(""); setInterim(""); transition(STATES.LISTENING);
      try {
        const text = await speechInput.listen({ onInterim: v => { setInterim(v); setInput(v); } });
        setInput(text); transition(STATES.IDLE); await send(text);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Microphone recognition failed.";
        if (!/did not catch/i.test(msg)) setError(msg);
        transition(STATES.IDLE);
      }
    }, [send, speechInput, speechOutput, state, transition]);

    const resetConversation = useCallback(() => {
      speechOutput.stop(); speechInput.stop(); setMessages([]); setError(""); setInput(""); setInterim("");
      transition(STATES.IDLE);
      try { sessionStorage.removeItem("hermes.digitalHuman.conversation.v2"); } catch { /* ignore */ }
      window.location.reload();
    }, [speechInput, speechOutput, transition]);

    return h("main", { className: "dh2-page" },
      h("header", { className: "dh2-header" },
        h("div", null,
          h("div", { className: "dh2-kicker" }, "HERMES // INTERACTIVE DIGITAL HUMAN"),
          h("h1", null, "Digital Human"),
          h("p", null, "A face-to-face interface to Hermes with eye contact, facial motion, speech and text — while the agent remains server-side.")),
        h("button", { type: "button", className: "dh2-new", onClick: resetConversation }, "NEW SESSION")),
      h(FeatureStrip, { health, micSupported: speechInput.supported, voiceSupported: speechOutput.supported, mode }),
      h("div", { className: "dh2-workspace" },
        h(AvatarStage, { controller, state, mode, onModeChange: changeMode }),
        h("section", { className: "dh2-chat", "aria-label": "Conversation with Hermes" },
          h("div", { className: "dh2-chat__header" },
            h("div", null, h("span", { className: "dh2-kicker" }, "LIVE CHANNEL"),
              h("strong", { dir: "auto" }, state === STATES.LISTENING && interim ? interim : "Conversation")),
            h(StatusPill, { state })),
          h(Transcript, { messages, thinking: state === STATES.THINKING, endRef }),
          error && h("div", { className: "dh2-error", role: "alert" },
            h("div", null, h("strong", null, "Connection issue"), h("span", null, error)),
            h("button", { type: "button", onClick: () => { setError(""); transition(STATES.IDLE); } }, "Dismiss")),
          h(Composer, {
            value: input, onChange: setInput, onSubmit: () => send(), onMic: handleMic,
            micSupported: speechInput.supported, listening: state === STATES.LISTENING,
            busy: state === STATES.THINKING, voiceEnabled,
            onToggleVoice: () => setVoiceEnabled(v => {
              if (v) { speechOutput.stop(); controller.setViseme({ open: 0.03, round: 0, wide: 0.2, jaw: 0 }); transition(STATES.IDLE); }
              return !v;
            }),
            onStopVoice: () => { speechOutput.stop(); controller.setViseme({ open: 0.03, round: 0, wide: 0.2, jaw: 0 }); transition(STATES.IDLE); },
          }))),
      h("footer", { className: "dh2-footer" },
        h("span", null, "Renderer: local procedural WebGL"),
        h("span", null, "Face: viseme + blink + gaze channels"),
        h("span", null, "Voice: browser STT/TTS adapter"),
        h("span", null, "AI: Hermes backend")));
  }

  REGISTRY.register("hermes-avatar", DigitalHumanPage);
})();