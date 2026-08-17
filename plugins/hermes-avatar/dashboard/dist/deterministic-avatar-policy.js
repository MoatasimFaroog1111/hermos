(function () {
  "use strict";

  const STORAGE_KEY = "hermes.digitalHuman.animationPolicy.v1";
  const RUNTIME_KEY = "__HERMES_AVATAR_RUNTIME_POLICY__";
  const RENDERER_KEY = "__HERMES_AVATAR_RENDERER__";
  const PATCH_FLAG = "__hermesDeterministicPolicyPatched";

  const STATE_ROLE = Object.freeze({
    idle: "idle",
    listening: "listening",
    thinking: "thinking",
    speaking: "speaking",
    error: "error",
  });

  const SEMANTIC_CLIP_PATTERNS = Object.freeze({
    idle: [/\bidle\b/i, /standing[_ -]?relax/i, /\bstand\b/i, /\bwait\b/i],
    listening: [/\blisten/i, /attention/i],
    thinking: [/\bthink/i, /ponder/i, /consider/i],
    speaking: [/\bspeak/i, /\btalk/i, /explain/i, /present/i],
    error: [/concern/i, /warning/i, /afraid/i],
  });

  const FACE_ALIASES = Object.freeze({
    blinkLeft: ["eyeBlinkLeft", "EyeBlinkLeft", "blinkLeft"],
    blinkRight: ["eyeBlinkRight", "EyeBlinkRight", "blinkRight"],
    jaw: ["jawOpen", "JawOpen", "mouthOpen", "viseme_aa", "viseme_DD", "viseme_kk"],
    round: ["mouthFunnel", "mouthPucker", "viseme_O", "viseme_U"],
    wide: ["mouthStretchLeft", "mouthStretchRight", "viseme_E", "viseme_I"],
    smile: ["mouthSmileLeft", "mouthSmileRight", "mouthSmile"],
    brow: ["browInnerUp", "browOuterUpLeft", "browOuterUpRight"],
  });

  const ARKIT_52 = Object.freeze([
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft",
    "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight", "eyeSquintLeft", "eyeSquintRight",
    "eyeWideLeft", "eyeWideRight", "jawForward", "jawLeft", "jawOpen", "jawRight",
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthFunnel", "mouthLeft", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthPressLeft",
    "mouthPressRight", "mouthPucker", "mouthRight", "mouthRollLower", "mouthRollUpper",
    "mouthShrugLower", "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft",
    "mouthStretchRight", "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight",
    "tongueOut",
  ]);

  const LIP_SYNC_REQUIRED = Object.freeze([
    "jawOpen",
    "mouthFunnel",
    "mouthPucker",
    "mouthStretchLeft",
    "mouthStretchRight",
  ]);

  function normalizeName(value) {
    return String(value || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  }

  function safeParseMap(raw) {
    if (!raw) return {};
    try {
      const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
      const result = {};
      for (const [role, target] of Object.entries(parsed)) {
        if (!Object.prototype.hasOwnProperty.call(STATE_ROLE, role)) continue;
        if (typeof target === "string" && target.trim()) result[role] = target.trim();
        else if (Number.isInteger(target) && target >= 0) result[role] = target;
      }
      return result;
    } catch {
      return {};
    }
  }

  function readStoredMap() {
    const hostMap = safeParseMap(window.__HERMES_AVATAR_ANIMATION_MAP__);
    if (Object.keys(hostMap).length) return hostMap;
    try {
      return safeParseMap(window.localStorage?.getItem(STORAGE_KEY));
    } catch {
      return {};
    }
  }

  let configuredMap = readStoredMap();
  const activeRenderers = new Set();

  class DeterministicAnimationPolicy {
    constructor(clips) {
      this.clips = Array.isArray(clips) ? clips : [];
    }

    catalog() {
      return this.clips.map((clip, index) => ({
        index,
        name: String(clip?.name || `clip-${index}`),
        duration: Number.isFinite(clip?.duration) ? clip.duration : null,
      }));
    }

    explicitTarget(role) {
      return configuredMap[role];
    }

    resolveExplicit(target) {
      if (Number.isInteger(target)) return this.clips[target] || null;
      if (typeof target !== "string") return null;
      const normalized = normalizeName(target);
      return this.clips.find(clip => normalizeName(clip?.name) === normalized) || null;
    }

    resolveSemantic(role) {
      const patterns = SEMANTIC_CLIP_PATTERNS[role] || [];
      const matches = this.clips.filter(clip => {
        const name = String(clip?.name || "");
        return patterns.some(pattern => pattern.test(name));
      });
      return matches.length === 1 ? matches[0] : null;
    }

    resolve(role) {
      const explicit = this.resolveExplicit(this.explicitTarget(role));
      if (explicit) return explicit;
      return this.resolveSemantic(role);
    }
  }

  function faceCapabilities(renderer) {
    const keys = new Set(Array.from(renderer?.morphBindings?.keys?.() || []));
    const present = ARKIT_52.filter(name => keys.has(normalizeName(name)));
    const missingLipSync = LIP_SYNC_REQUIRED.filter(name => !keys.has(normalizeName(name)));
    return {
      morphTargetNames: Array.from(keys),
      morphTargetCount: keys.size,
      arkitPresent: present.length,
      arkitTotal: ARKIT_52.length,
      arkitCoverage: ARKIT_52.length ? present.length / ARKIT_52.length : 0,
      lipSyncReady: missingLipSync.length === 0,
      missingLipSync,
    };
  }

  function patchRendererModule(moduleValue) {
    const Renderer = moduleValue?.ThreeAvatarRenderer;
    if (!Renderer?.prototype || Renderer.prototype[PATCH_FLAG]) return moduleValue;
    Renderer.prototype[PATCH_FLAG] = true;

    const originalLoadGLB = Renderer.prototype.loadGLB;
    const originalApplyCharacterMotion = Renderer.prototype.applyCharacterMotion;
    const originalApplyGLBSignals = Renderer.prototype.applyGLBSignals;
    const originalDestroy = Renderer.prototype.destroy;

    Renderer.prototype.loadGLB = async function hermesDeterministicLoadGLB(url) {
      let capturedGLTF = null;
      const OriginalLoader = this.GLTFLoader;

      if (typeof OriginalLoader === "function") {
        const renderer = this;
        this.GLTFLoader = class CapturingGLTFLoader extends OriginalLoader {
          async loadAsync(...args) {
            const gltf = await super.loadAsync(...args);
            capturedGLTF = gltf;
            return gltf;
          }
        };
        try {
          await originalLoadGLB.call(this, url);
        } finally {
          renderer.GLTFLoader = OriginalLoader;
        }
      } else {
        await originalLoadGLB.call(this, url);
      }

      this.__hermesAnimationClips = Array.isArray(capturedGLTF?.animations)
        ? capturedGLTF.animations.slice()
        : [];
      this.__hermesAnimationPolicy = new DeterministicAnimationPolicy(this.__hermesAnimationClips);
      this.__hermesAnimationRole = "";
      this.__hermesAnimationAction = null;
      this.__hermesAnimationClip = null;
      this.__hermesFaceCapabilities = faceCapabilities(this);

      // The legacy renderer starts the first clip as an idle fallback. That is
      // deliberately disabled here: a generic Tripo name such as NlaTrack is
      // not a semantic contract. We only play an explicitly mapped clip or one
      // whose name has one unique semantic match.
      if (this.mixer) this.mixer.stopAllAction();
      this.idleAction = null;
      activeRenderers.add(this);
      this.__hermesSyncAnimation?.(true);
    };

    Renderer.prototype.__hermesResolveRole = function hermesResolveRole() {
      const requested = String(this.signals?.animationRole || "").trim().toLowerCase();
      if (Object.prototype.hasOwnProperty.call(STATE_ROLE, requested)) return requested;
      const state = String(this.signals?.state || "idle").trim().toLowerCase();
      return STATE_ROLE[state] || "idle";
    };

    Renderer.prototype.__hermesSyncAnimation = function hermesSyncAnimation(force) {
      if (!this.mixer || !this.__hermesAnimationPolicy) return;
      const role = this.__hermesResolveRole();
      const clip = this.__hermesAnimationPolicy.resolve(role);
      const currentName = String(this.__hermesAnimationClip?.name || "");
      const nextName = String(clip?.name || "");
      if (!force && this.__hermesAnimationRole === role && currentName === nextName) return;

      const previous = this.__hermesAnimationAction;
      this.__hermesAnimationRole = role;
      this.__hermesAnimationClip = clip || null;
      this.__hermesAnimationAction = null;

      if (!clip) {
        if (previous) previous.fadeOut(0.18);
        return;
      }

      const next = this.mixer.clipAction(clip);
      if (next === previous && next.isRunning?.()) return;
      next.enabled = true;
      next.reset();
      if (this.THREE?.LoopRepeat !== undefined) next.setLoop(this.THREE.LoopRepeat, Infinity);
      next.clampWhenFinished = false;
      next.fadeIn(0.22).play();
      if (previous && previous !== next) previous.fadeOut(0.22);
      this.__hermesAnimationAction = next;
    };

    Renderer.prototype.applyCharacterMotion = function hermesPolicyCharacterMotion(time, deltaTime) {
      this.__hermesSyncAnimation?.(false);
      return originalApplyCharacterMotion.call(this, time, deltaTime);
    };

    Renderer.prototype.applyGLBSignals = function hermesArkitAwareSignals() {
      const signals = this.signals || {};
      this.setMorph(FACE_ALIASES.blinkLeft, Number(signals.blink) || 0);
      this.setMorph(FACE_ALIASES.blinkRight, Number(signals.blink) || 0);
      this.setMorph(
        FACE_ALIASES.jaw,
        Math.max(Number(signals.jaw) || 0, (Number(signals.mouthOpen) || 0) * 0.78),
      );
      this.setMorph(FACE_ALIASES.round, Number(signals.mouthRound) || 0);
      this.setMorph(FACE_ALIASES.wide, Number(signals.mouthWide) || 0);
      this.setMorph(FACE_ALIASES.smile, Number(signals.smile) || 0);
      this.setMorph(FACE_ALIASES.brow, Number(signals.browLift) || 0);

      // Preserve any future renderer-specific channels that are not part of
      // this ARKit/viseme adapter. The current implementation is equivalent,
      // but keeping the reference makes this patch forward compatible.
      void originalApplyGLBSignals;
    };

    Renderer.prototype.destroy = function hermesPolicyDestroy(...args) {
      activeRenderers.delete(this);
      return originalDestroy.apply(this, args);
    };

    return moduleValue;
  }

  function installRendererInterceptor() {
    const current = window[RENDERER_KEY];
    if (current) {
      patchRendererModule(current);
      return;
    }

    const descriptor = Object.getOwnPropertyDescriptor(window, RENDERER_KEY);
    if (descriptor && descriptor.configurable === false) return;

    let value = descriptor?.value;
    Object.defineProperty(window, RENDERER_KEY, {
      configurable: true,
      enumerable: true,
      get() {
        return value;
      },
      set(next) {
        value = patchRendererModule(next);
      },
    });
  }

  function setAnimationMap(nextMap) {
    configuredMap = safeParseMap(nextMap);
    try {
      window.localStorage?.setItem(STORAGE_KEY, JSON.stringify(configuredMap));
    } catch {
      // Local persistence is optional; the in-memory policy still applies.
    }
    for (const renderer of activeRenderers) {
      renderer.__hermesAnimationPolicy = new DeterministicAnimationPolicy(
        renderer.__hermesAnimationClips || [],
      );
      renderer.__hermesSyncAnimation?.(true);
    }
    return { ...configuredMap };
  }

  function runtimeSnapshot() {
    return Array.from(activeRenderers).map(renderer => ({
      animationRole: renderer.__hermesAnimationRole || "idle",
      activeClip: renderer.__hermesAnimationClip?.name || "",
      animationCatalog: renderer.__hermesAnimationPolicy?.catalog?.() || [],
      face: renderer.__hermesFaceCapabilities || faceCapabilities(renderer),
    }));
  }

  window[RUNTIME_KEY] = Object.freeze({
    version: "1.0.0",
    deterministic: true,
    getAnimationMap: () => ({ ...configuredMap }),
    setAnimationMap,
    clearAnimationMap: () => setAnimationMap({}),
    snapshot: runtimeSnapshot,
    requiredFaceStandard: "ARKit-52-compatible morph targets",
  });

  installRendererInterceptor();
})();
