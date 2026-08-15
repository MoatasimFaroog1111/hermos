(function () {
  "use strict";

  const API_FLAG = "__HERMES_HUMAN_BEHAVIOR__";
  const PATCH_FLAG = Symbol.for("hermes.avatar.humanBehaviorPatched");
  const ENGINE_KEY = Symbol.for("hermes.avatar.humanBehaviorEngine");

  if (window[API_FLAG]) return;

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const randomBetween = (min, max) => min + Math.random() * (max - min);
  const chance = probability => Math.random() < probability;
  const expLerp = (current, target, speed, deltaTime) => {
    const alpha = 1 - Math.exp(-Math.max(0, deltaTime) * speed);
    return current + (target - current) * alpha;
  };

  function smoothPulse(age, duration) {
    if (duration <= 0 || age < 0 || age > duration) return 0;
    const phase = clamp(age / duration, 0, 1);
    return Math.sin(phase * Math.PI);
  }

  function speechEnergy(signals = {}) {
    if (signals.state !== "speaking") return 0;
    const mouthOpen = clamp(Number(signals.mouthOpen) || 0, 0, 1);
    const jaw = clamp(Number(signals.jaw) || 0, 0, 1);
    const mouthWide = clamp(Number(signals.mouthWide) || 0, 0, 1);
    return clamp(0.15 + mouthOpen * 0.48 + jaw * 0.32 + mouthWide * 0.10, 0, 1);
  }

  class IntervalGate {
    constructor(minSeconds, maxSeconds) {
      this.minSeconds = minSeconds;
      this.maxSeconds = maxSeconds;
      this.remaining = randomBetween(minSeconds, maxSeconds);
    }

    reset(minSeconds = this.minSeconds, maxSeconds = this.maxSeconds) {
      this.remaining = randomBetween(minSeconds, maxSeconds);
    }

    tick(deltaTime, minSeconds = this.minSeconds, maxSeconds = this.maxSeconds) {
      this.remaining -= deltaTime;
      if (this.remaining > 0) return false;
      this.remaining = randomBetween(minSeconds, maxSeconds);
      return true;
    }
  }

  class AttentionController {
    constructor() {
      this.yaw = 0;
      this.pitch = 0;
      this.targetYaw = 0;
      this.targetPitch = 0;
      this.breakGate = new IntervalGate(1.8, 4.6);
      this.state = "idle";
      this.stateAge = 0;
    }

    enter(state) {
      if (state === this.state) return;
      this.state = state || "idle";
      this.stateAge = 0;
      if (this.state === "thinking") {
        this.targetYaw = randomBetween(-0.18, 0.18);
        this.targetPitch = randomBetween(-0.08, 0.05);
        this.breakGate.reset(1.1, 2.4);
      } else if (this.state === "listening") {
        this.targetYaw = randomBetween(-0.035, 0.035);
        this.targetPitch = randomBetween(-0.02, 0.025);
        this.breakGate.reset(2.2, 4.8);
      } else if (this.state === "speaking") {
        this.targetYaw = randomBetween(-0.055, 0.055);
        this.targetPitch = randomBetween(-0.025, 0.03);
        this.breakGate.reset(2.4, 5.5);
      } else {
        this.targetYaw = randomBetween(-0.07, 0.07);
        this.targetPitch = randomBetween(-0.035, 0.035);
        this.breakGate.reset(2.8, 6.2);
      }
    }

    pickTarget() {
      if (this.state === "thinking") {
        const side = chance(0.5) ? -1 : 1;
        this.targetYaw = side * randomBetween(0.09, 0.24);
        this.targetPitch = randomBetween(-0.10, 0.055);
        return;
      }
      if (this.state === "listening") {
        this.targetYaw = randomBetween(-0.045, 0.045);
        this.targetPitch = randomBetween(-0.03, 0.025);
        return;
      }
      if (this.state === "speaking") {
        const glance = chance(0.18);
        this.targetYaw = glance ? randomBetween(-0.12, 0.12) : randomBetween(-0.055, 0.055);
        this.targetPitch = randomBetween(-0.035, 0.035);
        return;
      }
      this.targetYaw = randomBetween(-0.095, 0.095);
      this.targetPitch = randomBetween(-0.05, 0.04);
    }

    update(deltaTime, state, pointerActive, pointerYaw, pointerPitch) {
      this.enter(state);
      this.stateAge += deltaTime;

      if (pointerActive) {
        this.targetYaw = clamp(pointerYaw, -0.42, 0.42);
        this.targetPitch = clamp(pointerPitch, -0.24, 0.24);
      } else if (this.breakGate.tick(deltaTime)) {
        this.pickTarget();
      }

      const speed = pointerActive ? 10.5 : this.state === "thinking" ? 2.7 : 4.4;
      this.yaw = expLerp(this.yaw, this.targetYaw, speed, deltaTime);
      this.pitch = expLerp(this.pitch, this.targetPitch, speed, deltaTime);
      return { yaw: this.yaw, pitch: this.pitch };
    }
  }

  class SaccadeController {
    constructor() {
      this.gate = new IntervalGate(0.22, 1.05);
      this.x = 0;
      this.y = 0;
      this.targetX = 0;
      this.targetY = 0;
    }

    update(deltaTime, state) {
      const min = state === "thinking" ? 0.18 : 0.28;
      const max = state === "listening" ? 0.85 : 1.25;
      if (this.gate.tick(deltaTime, min, max)) {
        const amplitude = state === "thinking" ? 0.028 : 0.018;
        this.targetX = randomBetween(-amplitude, amplitude);
        this.targetY = randomBetween(-amplitude * 0.55, amplitude * 0.55);
      }
      this.x = expLerp(this.x, this.targetX, 18, deltaTime);
      this.y = expLerp(this.y, this.targetY, 18, deltaTime);
      return { x: this.x, y: this.y };
    }
  }

  class BreathController {
    constructor() {
      this.phase = randomBetween(0, Math.PI * 2);
      this.rate = randomBetween(0.82, 1.02);
      this.rateTarget = this.rate;
      this.rateGate = new IntervalGate(5.0, 9.0);
    }

    update(deltaTime, state) {
      if (this.rateGate.tick(deltaTime)) {
        const base = state === "speaking" ? 1.02 : state === "thinking" ? 0.88 : 0.94;
        this.rateTarget = base * randomBetween(0.90, 1.10);
      }
      this.rate = expLerp(this.rate, this.rateTarget, 0.45, deltaTime);
      this.phase += deltaTime * this.rate * Math.PI;
      const primary = Math.sin(this.phase);
      const secondary = Math.sin(this.phase * 0.51 + 1.7) * 0.17;
      const shaped = Math.sign(primary) * Math.pow(Math.abs(primary), 1.15);
      return (shaped + secondary) * 0.0085;
    }
  }

  class PostureController {
    constructor() {
      this.gate = new IntervalGate(4.5, 9.5);
      this.yaw = 0;
      this.roll = 0;
      this.targetYaw = randomBetween(-0.008, 0.008);
      this.targetRoll = randomBetween(-0.006, 0.006);
    }

    update(deltaTime, state) {
      const stillness = state === "listening" ? 0.62 : state === "thinking" ? 0.78 : 1;
      if (this.gate.tick(deltaTime, 4.0, 10.0)) {
        this.targetYaw = randomBetween(-0.016, 0.016) * stillness;
        this.targetRoll = randomBetween(-0.010, 0.010) * stillness;
      }
      this.yaw = expLerp(this.yaw, this.targetYaw, 0.75, deltaTime);
      this.roll = expLerp(this.roll, this.targetRoll, 0.75, deltaTime);
      return { yaw: this.yaw, roll: this.roll };
    }
  }

  class GestureController {
    constructor() {
      this.state = "idle";
      this.stateAge = 0;
      this.nextSpeechGesture = randomBetween(0.45, 1.0);
      this.nextListeningNod = randomBetween(1.6, 3.8);
      this.gestureAge = Infinity;
      this.gestureDuration = 0.55;
      this.gestureSign = 1;
      this.gestureStrength = 0;
      this.listeningAge = Infinity;
      this.listeningDuration = 0.34;
      this.listeningStrength = 0;
    }

    enter(state) {
      if (state === this.state) return;
      this.state = state || "idle";
      this.stateAge = 0;
      this.nextSpeechGesture = randomBetween(0.35, 0.9);
      this.nextListeningNod = randomBetween(1.2, 2.8);
      if (this.state === "speaking") this.triggerSpeech(0.45);
      if (this.state === "listening" && chance(0.35)) this.triggerListening(0.45);
    }

    triggerSpeech(strength) {
      this.gestureAge = 0;
      this.gestureDuration = randomBetween(0.42, 0.78);
      this.gestureSign = chance(0.5) ? -1 : 1;
      this.gestureStrength = clamp(strength * randomBetween(0.72, 1.05), 0, 1);
    }

    triggerListening(strength = 0.6) {
      this.listeningAge = 0;
      this.listeningDuration = randomBetween(0.26, 0.42);
      this.listeningStrength = clamp(strength * randomBetween(0.75, 1.10), 0, 1);
    }

    update(deltaTime, state, speech) {
      this.enter(state);
      this.stateAge += deltaTime;
      this.gestureAge += deltaTime;
      this.listeningAge += deltaTime;

      if (state === "speaking") {
        this.nextSpeechGesture -= deltaTime;
        if (this.nextSpeechGesture <= 0) {
          this.triggerSpeech(0.35 + speech * 0.65);
          this.nextSpeechGesture = randomBetween(0.55, 1.45) / Math.max(0.45, 0.65 + speech);
        }
      }

      if (state === "listening") {
        this.nextListeningNod -= deltaTime;
        if (this.nextListeningNod <= 0) {
          this.triggerListening(randomBetween(0.35, 0.75));
          this.nextListeningNod = randomBetween(1.8, 4.8);
        }
      }

      const speechEnvelope = smoothPulse(this.gestureAge, this.gestureDuration) * this.gestureStrength;
      const listenEnvelope = smoothPulse(this.listeningAge, this.listeningDuration) * this.listeningStrength;
      const headNod = -speechEnvelope * 0.030 - listenEnvelope * 0.026;
      const headTurn = speechEnvelope * this.gestureSign * 0.034;
      const headRoll = speechEnvelope * this.gestureSign * 0.014;
      const arm = speechEnvelope * (0.055 + speech * 0.055);

      return {
        headNod,
        headTurn,
        headRoll,
        arm,
        side: this.gestureSign,
      };
    }
  }

  class HumanBehaviorEngine {
    constructor(renderer) {
      this.renderer = renderer;
      this.attention = new AttentionController();
      this.saccades = new SaccadeController();
      this.breath = new BreathController();
      this.posture = new PostureController();
      this.gestures = new GestureController();
      this.state = "idle";
      this.stateAge = 0;
      this.microHeadYaw = 0;
      this.microHeadPitch = 0;
      this.microGate = new IntervalGate(1.4, 3.5);
    }

    updateState(deltaTime, state) {
      if (state !== this.state) {
        this.state = state || "idle";
        this.stateAge = 0;
      } else {
        this.stateAge += deltaTime;
      }
    }

    updateMicroHead(deltaTime) {
      if (this.microGate.tick(deltaTime, 1.2, 3.8)) {
        const stateScale = this.state === "listening" ? 0.55 : this.state === "thinking" ? 1.15 : 0.82;
        this.microHeadYaw = randomBetween(-0.016, 0.016) * stateScale;
        this.microHeadPitch = randomBetween(-0.010, 0.010) * stateScale;
      }
      return {
        yaw: this.microHeadYaw,
        pitch: this.microHeadPitch,
      };
    }

    sample(deltaTime) {
      const r = this.renderer;
      const signals = r.signals || {};
      const state = signals.state || "idle";
      this.updateState(deltaTime, state);

      if (!r.pointerActive) {
        r.pointerYaw *= Math.exp(-deltaTime * 2.8);
        r.pointerPitch *= Math.exp(-deltaTime * 2.8);
      }

      const attention = this.attention.update(
        deltaTime,
        state,
        Boolean(r.pointerActive),
        r.pointerYaw,
        r.pointerPitch,
      );
      const saccade = this.saccades.update(deltaTime, state);
      const breathing = this.breath.update(deltaTime, state);
      const posture = this.posture.update(deltaTime, state);
      const speech = speechEnergy(signals);
      const gesture = this.gestures.update(deltaTime, state, speech);
      const micro = this.updateMicroHead(deltaTime);

      const gazeYaw = attention.yaw + saccade.x;
      const gazePitch = attention.pitch + saccade.y;
      r.currentYaw = expLerp(r.currentYaw || 0, gazeYaw, r.pointerActive ? 13 : 8, deltaTime);
      r.currentPitch = expLerp(r.currentPitch || 0, gazePitch, r.pointerActive ? 13 : 8, deltaTime);
      r.attentionPulse *= Math.exp(-deltaTime * 3.7);

      const attentionNod = Math.sin((1 - r.attentionPulse) * Math.PI * 1.6)
        * 0.030 * r.attentionPulse;

      const stateHeadPitch = state === "listening"
        ? 0.018
        : state === "thinking"
          ? -0.010
          : 0;
      const stateHeadRoll = state === "listening" ? 0.012 : 0;
      const motionScale = r.reducedMotion ? 0.25 : 1;

      return {
        motionScale,
        gazeYaw: r.currentYaw,
        gazePitch: r.currentPitch,
        breath: breathing * motionScale,
        postureYaw: posture.yaw * motionScale,
        postureRoll: posture.roll * motionScale,
        headYaw: (micro.yaw + gesture.headTurn) * motionScale,
        headPitch: (micro.pitch + gesture.headNod + attentionNod + stateHeadPitch) * motionScale,
        headRoll: (gesture.headRoll + stateHeadRoll) * motionScale,
        arm: gesture.arm * motionScale,
        armSide: gesture.side,
        speech,
      };
    }

    apply(deltaTime) {
      const r = this.renderer;
      const pose = this.sample(deltaTime);

      if (r.procedural) {
        r.applyMotion(r.head, {
          rx: pose.gazePitch * 0.70 + pose.headPitch,
          ry: pose.gazeYaw * 0.84 + pose.headYaw,
          rz: pose.headRoll,
        });
        r.applyMotion(r.root, {
          ry: pose.postureYaw + pose.headYaw * 0.10,
          rz: pose.postureRoll * 0.45,
          py: pose.breath * 0.46,
        });
        return;
      }

      const lookNode = r.rig.head || r.rig.neck || r.rig.chest || r.root;
      r.applyMotion(lookNode, {
        rx: pose.gazePitch * 0.80 + pose.headPitch,
        ry: pose.gazeYaw * 0.92 + pose.headYaw,
        rz: pose.headRoll,
      });

      if (r.rig.neck && r.rig.neck !== lookNode) {
        r.applyMotion(r.rig.neck, {
          rx: pose.gazePitch * 0.17 + pose.headPitch * 0.20,
          ry: pose.gazeYaw * 0.22 + pose.headYaw * 0.20,
          rz: pose.headRoll * 0.18,
        });
      }

      const torso = r.rig.chest || r.rig.hips || r.root;
      if (torso && torso !== lookNode) {
        r.applyMotion(torso, {
          rx: pose.breath * 0.42 + pose.speech * 0.008,
          ry: pose.postureYaw + pose.headYaw * 0.28,
          rz: pose.postureRoll + pose.headRoll * 0.32,
          py: pose.breath * 0.22,
        });
      }

      const arm = pose.arm;
      const leftWeight = pose.armSide > 0 ? 1 : 0.58;
      const rightWeight = pose.armSide < 0 ? 1 : 0.58;
      r.applyMotion(r.leftShoulder, {
        rz: arm * 0.42 * leftWeight,
        rx: -arm * 0.20,
      });
      r.applyMotion(r.rightShoulder, {
        rz: -arm * 0.42 * rightWeight,
        rx: -arm * 0.20,
      });
      r.applyMotion(r.leftUpperArm, {
        rz: arm * 0.66 * leftWeight,
        rx: -arm * 0.30,
      });
      r.applyMotion(r.rightUpperArm, {
        rz: -arm * 0.66 * rightWeight,
        rx: -arm * 0.30,
      });

      const eyeYaw = clamp(pose.gazeYaw * 0.35, -0.10, 0.10);
      const eyePitch = clamp(pose.gazePitch * 0.28, -0.07, 0.07);
      if (r.eyeLeft && r.eyeLeft !== lookNode) {
        r.applyMotion(r.eyeLeft, { rx: eyePitch, ry: eyeYaw });
      }
      if (r.eyeRight && r.eyeRight !== lookNode && r.eyeRight !== r.eyeLeft) {
        r.applyMotion(r.eyeRight, { rx: eyePitch, ry: eyeYaw });
      }

      if (!r.rig.head && !r.rig.neck && !r.rig.chest) {
        r.applyMotion(r.root, {
          rx: pose.gazePitch * 0.12 + pose.headPitch * 0.22,
          ry: pose.gazeYaw * 0.30 + pose.headYaw * 0.30 + pose.postureYaw,
          rz: pose.headRoll * 0.28 + pose.postureRoll,
          py: pose.breath * 0.18,
        });
      }
    }

    destroy() {
      this.renderer = null;
    }
  }

  function engineFor(renderer) {
    if (!renderer[ENGINE_KEY]) renderer[ENGINE_KEY] = new HumanBehaviorEngine(renderer);
    return renderer[ENGINE_KEY];
  }

  function patchRenderer() {
    const rendererAPI = window.__HERMES_AVATAR_RENDERER__;
    const Renderer = rendererAPI?.ThreeAvatarRenderer;
    if (!Renderer?.prototype) return false;
    const prototype = Renderer.prototype;
    if (prototype[PATCH_FLAG]) return true;

    const originalMotion = prototype.applyCharacterMotion;
    const originalDestroy = prototype.destroy;

    Object.defineProperty(prototype, PATCH_FLAG, { value: true });
    prototype.applyCharacterMotion = function humanCharacterMotion(_time, deltaTime) {
      try {
        engineFor(this).apply(deltaTime);
      } catch (error) {
        console.warn("[hermes-avatar] human behavior fallback", error);
        return originalMotion.call(this, _time, deltaTime);
      }
    };

    prototype.destroy = function humanBehaviorDestroy() {
      try {
        this[ENGINE_KEY]?.destroy?.();
        this[ENGINE_KEY] = null;
      } catch {
        // Best-effort cleanup; renderer destruction must always continue.
      }
      return originalDestroy.call(this);
    };

    return true;
  }

  function installRendererHook() {
    if (patchRenderer()) return;

    const observer = new MutationObserver(records => {
      for (const record of records) {
        for (const node of record.addedNodes || []) {
          if (!(node instanceof HTMLScriptElement)) continue;
          if (!String(node.src || "").includes("three-avatar-renderer.js")) continue;
          node.addEventListener("load", () => patchRenderer(), { once: true, capture: true });
        }
      }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });

    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (patchRenderer() || attempts >= 600) {
        window.clearInterval(timer);
        observer.disconnect();
      }
    }, 50);
  }

  window[API_FLAG] = Object.freeze({
    HumanBehaviorEngine,
    AttentionController,
    SaccadeController,
    BreathController,
    PostureController,
    GestureController,
    patchRenderer,
    speechEnergy,
  });

  installRendererHook();
})();
